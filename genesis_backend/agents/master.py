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
# At the top of agents/master.py
from pathlib import Path

def _load_prompt(name: str) -> str:
    path = Path(__file__).parent.parent / "prompts" / f"{name}.md"
    return path.read_text(encoding="utf-8")

SYSTEM_PROMPT = _load_prompt("master")


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
- scout      → crawl documentation, API references, or release notes (provide a URL or search query)
- engineer   → write and execute a Python script in a secure E2B sandbox
- analyst    → pull structured data from AWS Cost Explorer or GCP Cloud Logging
- policy_guard → check whether a proposed fix is safe to auto-execute
- report     → generate the final PDF post-mortem (call this when confidence >= 0.85 and fix is done or blocked)
- end        → terminate immediately (only if something is catastrophically wrong)

DECISION RULES:
1. Always check prior incidents and runbooks before writing new scripts
2. Increase confidence only when multiple independent signals agree
3. Never propose a destructive action without routing through policy_guard first
4. Once confidence >= 0.85 and the fix is either applied or blocked, call report
5. If retry_count >= 3, lower ambition — simplify the script or change approach

RESPONSE FORMAT — always respond with valid JSON only, no prose outside the JSON:
{
  "reasoning": "step-by-step thinking about what the evidence shows",
  "next_worker": "scout|engineer|analyst|policy_guard|report|end",
  "instruction": "precise instruction for the chosen worker",
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

    context = _build_context(state)

    response = llm.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=context),
    ])

    parsed = _parse_response(response.content)

    log_entry = f"[Master] {parsed.get('reasoning', 'No reasoning provided')[:300]}"
    logger.info(log_entry)

    return {
        **state,
        "current_worker": "master",
        "step_log": [log_entry],
        "root_cause": parsed.get("root_cause"),
        "confidence_score": float(parsed.get("confidence_score", 0.0)),
        "corroborating_signals": parsed.get("corroborating_signals", []),
        "proposed_fix": parsed.get("proposed_fix"),
        "_next_worker": parsed.get("next_worker", "end"),
        "_worker_instruction": parsed.get("instruction", ""),
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
        # Model may have wrapped JSON in ```json ... ```
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
    return "\n\n".join(parts)
