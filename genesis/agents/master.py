"""
master.py — The Genesis Orchestrator.

Responsibilities:
- Receive the full AgentState after each worker completes
- Reason about what to do next
- Update confidence score and root cause hypothesis
- Route to the correct next worker
- Decide when to stop and generate the report

The master NEVER executes anything directly. It only reasons and delegates.
"""

import json
import re
import os
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage
from loguru import logger
from langchain_google_genai import ChatGoogleGenerativeAI
from core.state import AgentState
from core.config import config
from pathlib import Path

# ── Arize AX tracing — must be initialised BEFORE any google.genai import ────
from arize.otel import register
# from openinference.instrumentation.google_genai import GoogleGenAIInstrumentor
from openinference.instrumentation.langchain import LangChainInstrumentor


tracer_provider = register(
    space_id=os.environ["ARIZE_SPACE_ID"],
    api_key=os.environ["ARIZE_API_KEY"],
    project_name=os.environ.get("ARIZE_PROJECT_NAME", "genesis-compliance"),
    endpoint="https://otlp.eu-west-1a.arize.com",
)
# GoogleGenAIInstrumentor().instrument(tracer_provider=tracer_provider)
LangChainInstrumentor().instrument(tracer_provider=tracer_provider)
# ─────────────────────────────────────────────────────────────────────────────


logger.info("[Arize] Tracing initialised — project: genesis-compliance")

# Bayesian selector — imported lazily so it degrades gracefully if disabled
_bayesian_selector = None

def _get_bayesian_selector():
    global _bayesian_selector
    if _bayesian_selector is None and config.BAYESIAN_SELECTOR_ENABLED:
        try:
            from tools.bayesian_selector import BayesianSelector
            _bayesian_selector = BayesianSelector()
        except Exception as exc:
            logger.warning(f"[Master] Bayesian selector unavailable: {exc}")
    return _bayesian_selector

def _load_prompt(name: str) -> str:
    path = Path(__file__).parent.parent / "prompts" / f"{name}.md"
    return path.read_text(encoding="utf-8")

# ── LLM client ───────────────────────────────────────────────────────────────
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-lite",
    google_api_key=config.GEMINI_API_KEY,
    temperature=0,
)

SYSTEM_PROMPT = """You are Genesis Orchestrator, an autonomous SRE incident response agent.

YOUR ROLE:
- Investigate infrastructure incidents by delegating to specialist workers
- Build a confident root cause hypothesis by collecting corroborating evidence
- Propose and (when safe and confident) execute fixes
- Produce a structured post-mortem when the investigation is complete

WORKERS YOU CAN CALL:
- scout      → scrape a SPECIFIC URL only (e.g. https://docs.mongodb.com/...). CANNOT do keyword searches.
- engineer   → write and execute a Python script in a secure E2B sandbox
- analyst    → pull structured data from AWS Cost Explorer or GCP Cloud Logging
- policy_guard → check whether a proposed fix is safe to auto-execute
- report     → generate the final PDF post-mortem (call this when confidence >= 0.85 and fix is done or blocked)
- end        → terminate immediately (only if something is catastrophically wrong)

CRITICAL CONSTRAINTS:
- MONGODB: The MONGODB_URI and MONGODB_DB environment variables are ALREADY INJECTED into every engineer sandbox. Do NOT call scout to find connection strings or MongoDB docs — just write the Python script directly using pymongo.
- SCOUT LIMITATION: Scout can only scrape explicit URLs, NOT perform web searches. Never call scout with a search query like "how to connect to MongoDB" — it will fail. Only call scout if you have a direct documentation URL.
- If an engineer script fails due to a connection error, try a different query approach or reduce scope — do NOT call scout for help.

DECISION RULES:
1. For database investigations, go directly to engineer — all credentials are pre-configured
2. Increase confidence only when multiple independent signals agree
3. Never propose a destructive action without routing through policy_guard first
4. Once confidence >= 0.85 and the fix is either applied or blocked, call report
5. If retry_count >= 3, call report immediately with whatever evidence you have

ENGINEER INSTRUCTION RULE — THIS IS CRITICAL:
When next_worker is "engineer", the "instruction" field MUST contain the ACTUAL PYTHON CODE wrapped in a ```python fence.
DO NOT write prose like "Write a script to query...". The engineer cannot write code itself — it only executes what you provide.
If there is no ```python ... ``` block in the instruction, NOTHING will run and you will waste an iteration.

CORRECT example:
  "instruction": "```python\nfrom pymongo import MongoClient\nimport os\nclient = MongoClient(os.getenv('MONGODB_URI'))\ndb = client[os.getenv('MONGODB_DB', 'genesis_compliance')]\nresult = list(db.transactions.find({'status': 'approved'}).limit(5))\nfor r in result:\n    print(r)\n```"

WRONG example (will fail):
  "instruction": "Query the transactions collection for approved records"

RESPONSE FORMAT — always respond with valid JSON only, no prose outside the JSON:
{
  "reasoning": "step-by-step thinking about what the evidence shows",
  "next_worker": "scout|engineer|analyst|policy_guard|report|end",
  "instruction": "MUST contain actual ```python\\n...\\n``` code block when next_worker is engineer",
  "root_cause": "current best hypothesis as a single sentence, or null",
  "confidence_score": 0.0,
  "corroborating_signals": ["signal 1", "signal 2"],
  "proposed_fix": "the fix to apply described precisely, or null"
}
"""


def reason(state: AgentState) -> AgentState:
    """Main reasoning step — called after every worker completes."""
    iteration = state.get("retry_count", 0)
    logger.info(f"[Master] Reasoning. Iteration={iteration} | Confidence={state.get('confidence_score', 0.0):.2f}")

    # ── Hard-stop guard: too many failed retries → go straight to report/end ──
    if iteration >= config.MAX_SCRIPT_RETRIES:
        current_confidence = state.get("confidence_score", 0.0)
        next_worker = "report" if current_confidence >= 0.3 else "end"
        msg = (
            f"[Master] Retry limit ({config.MAX_SCRIPT_RETRIES}) reached — "
            f"routing to '{next_worker}' with confidence {current_confidence:.2f}"
        )
        logger.warning(msg)
        return {
            **state,
            "current_worker": "master",
            "step_log": [msg],
            "_next_worker": next_worker,
            "_worker_instruction": "Generate final report based on evidence collected so far.",
        }

    # ── Schema-first guard: always inspect the DB before writing investigation scripts ──
    scripts_executed = state.get("scripts_executed", [])
    db_keywords = [
        "database", "mongodb", "mongo", "collection", "transactions",
        "compliance", "audit", "employees", "customers", "approval",
        "sql", "postgres", "mysql", "dynamo",
    ]
    is_db_incident = any(
        word in state.get("incident_prompt", "").lower()
        for word in db_keywords
    )
    if len(scripts_executed) == 0 and is_db_incident:
        schema_script = '''```python
import os, sys
from pymongo import MongoClient

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB  = os.getenv("MONGODB_DB", "genesis_compliance")

try:
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=8000)
    client.admin.command("ping")
    db = client[MONGODB_DB]
    print("Connected:", MONGODB_DB)
except Exception as e:
    print("CONNECTION FAILED:", e)
    sys.exit(1)

print("\\n=== SCHEMA INSPECTION ===")
for name in sorted(db.list_collection_names()):
    count = db[name].count_documents({})
    sample = list(db[name].find().limit(1))
    fields = list(sample[0].keys()) if sample else []
    fields = [f for f in fields if f != "_id"]
    print(f"\\nCOLLECTION: {name}")
    print(f"  documents : {count}")
    print(f"  fields    : {fields}")
    if sample:
        row = {k: v for k, v in sample[0].items() if k != "_id"}
        print(f"  sample    : {row}")
```'''
        msg = "[Master] 🔍 Database incident detected — running schema inspection before any investigation"
        logger.info(msg)
        return {
            **state,
            "current_worker": "master",
            "step_log": [msg],
            "_next_worker": "engineer",
            "_worker_instruction": schema_script,
        }

    bayesian_suggestion = state.get("bayesian_suggestion", "")

    selector = _get_bayesian_selector()
    if selector and state.get("scripts_executed"):
        latest = state["scripts_executed"][-1]
        from tools.bayesian_selector import extract_keywords_from_output
        keywords = extract_keywords_from_output(
            latest.get("output", ""),
            latest.get("stderr", ""),
        )
        last_worker = state.get("current_worker", "")
        if last_worker and last_worker not in ("master", "memory_agent", "scribe"):
            selector.record_action(last_worker, keywords)

        bayesian_suggestion = selector.suggest()
        bayesian_beliefs = selector.belief_state.beliefs
        bayesian_entropy = selector.belief_state.entropy()
        bayesian_top_cause, _ = selector.belief_state.top_hypothesis()
    else:
        bayesian_beliefs = state.get("bayesian_beliefs", {})
        bayesian_entropy = state.get("bayesian_entropy", 0.0)
        bayesian_top_cause = state.get("bayesian_top_cause")

    context = _build_context({**state, "bayesian_suggestion": bayesian_suggestion})

    # ── LLM call with JSON retry loop ─────────────────────────────────────
    parsed = None
    last_raw = ""
    for attempt in range(3):
        try:
            messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=context)]

            if attempt > 0:
                messages.append(HumanMessage(content=(
                    f"Your previous response could not be parsed as JSON.\n"
                    f"Previous response was:\n{last_raw[:500]}\n\n"
                    "You MUST respond with ONLY a valid JSON object. "
                    "No prose, no markdown fences, no explanation outside the JSON. "
                    "Start your response with { and end with }."
                )))

            response = llm.invoke(messages)
            last_raw = response.content
            parsed = _parse_response(last_raw)

            if parsed.get("reasoning") != "JSON parse failure":
                break

            logger.warning(f"[Master] JSON parse failed on attempt {attempt + 1}/3")

        except Exception as exc:
            logger.error(f"[Master] LLM call failed on attempt {attempt + 1}: {exc}")

    if parsed is None or parsed.get("reasoning") == "JSON parse failure":
        logger.error("[Master] All JSON parse attempts failed — synthesising completion from current state")
        current_confidence = state.get("confidence_score", 0.0)
        parsed = {
            "next_worker": "report_generator" if current_confidence >= 0.4 else "end",
            "reasoning": "JSON parse failure after 3 retries — completing with current state",
            "confidence_score": current_confidence,
            "root_cause": state.get("root_cause") or "Could not be determined due to response format error",
            "corroborating_signals": state.get("corroborating_signals", []),
            "proposed_fix": state.get("proposed_fix"),
            "instruction": "",
        }

    log_entry = f"[Master] {parsed.get('reasoning', 'No reasoning provided')[:300]}"
    logger.info(log_entry)

    try:
        tracer_provider.force_flush()
    except Exception:
        pass
    
    return {
        **state,
        "current_worker": "master",
        "step_log": [log_entry],
        "root_cause": parsed.get("root_cause") or state.get("root_cause"),
        "confidence_score": float(parsed.get("confidence_score", state.get("confidence_score", 0.0))),
        "corroborating_signals": parsed.get("corroborating_signals", state.get("corroborating_signals", [])),
        "proposed_fix": parsed.get("proposed_fix") or state.get("proposed_fix"),
        "_next_worker": parsed.get("next_worker", "end"),
        "_worker_instruction": parsed.get("instruction", ""),
        "bayesian_beliefs": bayesian_beliefs,
        "bayesian_entropy": bayesian_entropy,
        "bayesian_top_cause": bayesian_top_cause,
        "bayesian_suggestion": bayesian_suggestion,
    }


def route_next(state: AgentState) -> str:
    """Conditional edge function — tells LangGraph which node to visit next."""
    if state.get("should_terminate"):
        return "end"
    return state.get("_next_worker", "end")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_response(content: str) -> dict:
    """Parse JSON from model response, handling markdown fences gracefully."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    logger.warning("[Master] Could not parse model response as JSON — routing to end")
    return {"next_worker": "end", "reasoning": "JSON parse failure", "confidence_score": 0.0}


def _build_context(state: AgentState) -> str:
    """Assemble all collected evidence into a single context string for the LLM."""
    scripts_summary = []
    for s in state.get("scripts_executed", []):
        scripts_summary.append({
            "success": s.get("success"),
            "output_preview": s.get("output", "")[:500],
            "stderr_preview": s.get("stderr", "")[:200],
        })

    parts = [
        f"INCIDENT: {state['incident_prompt']}",
        f"RETRY COUNT: {state.get('retry_count', 0)} / {config.MAX_SCRIPT_RETRIES}",
        f"CURRENT CONFIDENCE: {state.get('confidence_score', 0.0):.2f}",
        f"CURRENT ROOT CAUSE HYPOTHESIS: {state.get('root_cause', 'None yet')}",
        f"CORROBORATING SIGNALS: {json.dumps(state.get('corroborating_signals', []))}",
        f"PRIOR INCIDENTS (from memory): {json.dumps(state.get('prior_incidents', []))}",
        f"RUNBOOK CONTEXT: {state.get('documentation_context', 'Not yet retrieved')}",
        f"RAW LOGS: {state.get('raw_logs', 'Not yet collected')}",
        f"COST DATA: {json.dumps(state.get('raw_cost_data', {}))}",
        f"SCRIPTS EXECUTED: {json.dumps(scripts_summary)}",
        f"PROPOSED FIX: {state.get('proposed_fix', 'None yet')}",
        f"FIX BLOCKED REASON: {state.get('fix_blocked_reason', 'None')}",
        f"AWAITING HUMAN APPROVAL: {state.get('awaiting_human_approval', False)}",
        "STEP LOG (most recent 10 steps):",
        "\n".join(state.get("step_log", [])[-10:]),
    ]

    schema_context = state.get("schema_context")
    if schema_context:
        parts.insert(0, (
            "DATABASE SCHEMA (discovered at investigation start — USE THESE EXACT FIELD NAMES):\n"
            + schema_context
        ))

    memory_context = state.get("memory_context")
    if memory_context:
        parts.insert(4, f"MEMORY CONTEXT:\n{memory_context}")

    obsidian_context = state.get("obsidian_context")
    if obsidian_context:
        parts.insert(5, f"OBSIDIAN VAULT CONTEXT:\n{obsidian_context}")

    bayesian_suggestion = state.get("bayesian_suggestion")
    if bayesian_suggestion and config.BAYESIAN_SELECTOR_ENABLED:
        parts.append(bayesian_suggestion)

    return "\n\n".join(parts)