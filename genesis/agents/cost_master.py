"""
agents/cost_master.py
---------------------
Gemini reasoning brain for the Cloud Cost Optimization agent.
Mirrors master.py from Genesis but with:
- Bayesian waste belief state (confidence per waste category)
- Schema-first guard (reads BQ tables before any cost query)
- Hard-stop after MAX_RETRIES
- Arize tracing
"""

import os
import json
import asyncio
from typing import Any
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from core.cost_state import CostAgentState

# ── Arize tracing ─────────────────────────────────────────────────────────────
try:
    os.environ["OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT"] = "2000"
    os.environ["OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT"]   = "64"
    from arize.otel import register
    from openinference.instrumentation.langchain import LangChainInstrumentor
    register(
        space_id   = os.environ.get("ARIZE_SPACE_ID", ""),
        api_key    = os.environ.get("ARIZE_API_KEY", ""),
        project_name = os.environ.get("ARIZE_PROJECT_NAME", "genesis-cost"),
        endpoint   = "https://otlp.arize.com/v1",
    )
    LangChainInstrumentor().instrument()
    print("[CostMaster] Arize tracing active")
except Exception as e:
    print(f"[CostMaster] Arize tracing unavailable: {e}")

MAX_SCRIPT_RETRIES = 6

# ── Waste categories tracked by Bayesian belief state ─────────────────────────
WASTE_CATEGORIES = [
    "idle_vm",
    "oversized_vm",
    "overprovisioned_cloud_run",
    "orphaned_storage",
    "expensive_bq_jobs",
]

INITIAL_BELIEFS = {cat: 0.20 for cat in WASTE_CATEGORIES}  # uniform prior

# ── system prompt loader ──────────────────────────────────────────────────────

def _load_system_prompt() -> str:
    prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "cost_master.md")
    with open(prompt_path) as f:
        return f.read()

# ── Gemini LLM ────────────────────────────────────────────────────────────────

def _get_llm():
    return ChatGoogleGenerativeAI(
        model        = "gemini-2.0-flash",
        google_api_key = os.environ["GEMINI_API_KEY"],
        temperature  = 0.1,
        max_tokens   = 8192,
    )

# ── Bayesian belief updater ───────────────────────────────────────────────────

def _update_beliefs(beliefs: dict, output: str, findings: list) -> dict:
    """
    Naive Bayesian update: boost confidence for categories with evidence,
    decay others slightly. Real version would use likelihood ratios.
    """
    updated = dict(beliefs)
    output_lower = output.lower()

    signals = {
        "idle_vm":                  ["avg_cpu", "idle", "cpu utilization", "worker-"],
        "oversized_vm":             ["ram_utilization", "oversized", "recommended_type", "n1-standard"],
        "overprovisioned_cloud_run":["cloud_run", "requests_7d", "zero_requests", "last_request"],
        "orphaned_storage":         ["last_access_days", "orphan", "bucket", "gcs"],
        "expensive_bq_jobs":        ["bytes_processed", "gb_processed", "full_table_scan", "bq_job"],
    }

    for cat, keywords in signals.items():
        hits = sum(1 for kw in keywords if kw in output_lower)
        if hits >= 2:
            updated[cat] = min(0.97, updated[cat] + 0.25 * hits)
        elif hits == 1:
            updated[cat] = min(0.97, updated[cat] + 0.10)
        else:
            updated[cat] = max(0.05, updated[cat] - 0.05)

    # Also boost from explicitly named findings
    for finding in findings:
        cat = finding.get("category", "")
        if cat in updated:
            updated[cat] = min(0.97, updated[cat] + 0.15)

    # Normalise to keep values meaningful (not a true probability distribution,
    # more like independent confidence scores per category)
    return updated

# ── Schema inspection ─────────────────────────────────────────────────────────

SCHEMA_SCRIPT = '''
import json
from google.cloud import bigquery
import os

PROJECT_ID = os.environ["GCP_PROJECT_ID"]
DATASET    = os.environ.get("BQ_DATASET", "genesis_cost")
client     = bigquery.Client(project=PROJECT_ID)

tables = list(client.list_tables(f"{PROJECT_ID}.{DATASET}"))
schema_info = {}
for t in tables:
    tbl = client.get_table(t)
    schema_info[t.table_id] = {
        "fields": [f.name for f in tbl.schema],
        "num_rows": tbl.num_rows,
    }
print(json.dumps(schema_info, indent=2))
'''

# ── Main reasoning node ───────────────────────────────────────────────────────

async def cost_master_reason(state: CostAgentState) -> CostAgentState:
    """
    One reasoning step:
    1. On iteration 0, force schema inspection
    2. Build context from previous outputs + belief state
    3. Ask Gemini what to investigate next
    4. Parse script + updated findings from response
    """
    iteration  = state.get("iteration", 0)
    beliefs    = state.get("waste_beliefs", INITIAL_BELIEFS.copy())
    findings   = state.get("findings", [])
    last_output = state.get("last_output", "")
    history    = state.get("output_history", [])

    llm = _get_llm()
    system_prompt = _load_system_prompt()

    # ── iteration 0: force schema inspection ─────────────────────────────────
    if iteration == 0:
        print("[CostMaster] Iteration 0 — forcing schema inspection")
        return {
            **state,
            "scripts": [SCHEMA_SCRIPT],
            "phase": "schema_inspection",
            "waste_beliefs": beliefs,
        }

    # ── build belief state summary for Gemini ─────────────────────────────────
    belief_summary = "\n".join(
        f"  {cat}: {conf*100:.0f}% confidence"
        for cat, conf in sorted(beliefs.items(), key=lambda x: -x[1])
    )

    findings_summary = json.dumps(findings, indent=2) if findings else "None yet"

    history_text = ""
    for i, (script, output) in enumerate(history[-3:], 1):
        history_text += f"\n--- Execution {i} ---\nScript:\n{script[:400]}\nOutput:\n{output[:600]}\n"

    user_message = f"""
## Current Investigation State

**Iteration:** {iteration}
**Phase:** {state.get('phase', 'investigating')}

## Bayesian Waste Belief State
{belief_summary}

## Confirmed Findings So Far
{findings_summary}

## Last Script Output
{last_output[:3000] if last_output else 'No output yet'}

## Recent History (last 3 executions)
{history_text if history_text else 'None'}

## Instructions
Based on the evidence above, write the NEXT Python script to investigate.
- Focus on waste categories with low confidence that haven't been confirmed yet
- Use the exact BigQuery table names from the schema inspection
- Do NOT re-run queries that already returned good data
- If all 5 categories are confirmed at >80%, set phase to COMPLETE

Respond in this EXACT JSON format (no markdown, no backticks):
{{
  "reasoning": "Your chain-of-thought about what to investigate next",
  "script": "your complete python script here",
  "findings_update": [
    {{"category": "idle_vm", "count": 12, "total_monthly_waste": 1165.08, "evidence": "12 VMs with avg_cpu_14d < 3%", "recommendation": "..."}}
  ],
  "phase": "investigating|complete",
  "confidence_overall": 0.85
}}
"""

    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ])
        raw = response.content.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
            raw = re.sub(r"\n?```$", "", raw, flags=re.MULTILINE)
            raw = raw.strip()

        parsed = json.loads(raw)

        new_script   = parsed.get("script", "")
        new_findings = parsed.get("findings_update", [])
        phase        = parsed.get("phase", "investigating")
        reasoning    = parsed.get("reasoning", "")

        print(f"[CostMaster] Iteration {iteration} reasoning: {reasoning[:200]}")
        print(f"[CostMaster] Phase: {phase} | New findings: {len(new_findings)}")

        # Update beliefs based on last output + new findings
        updated_beliefs = _update_beliefs(beliefs, last_output, new_findings)

        # Merge findings (deduplicate by category)
        existing_cats = {f["category"] for f in findings}
        merged_findings = list(findings)
        for f in new_findings:
            if f["category"] not in existing_cats:
                merged_findings.append(f)
            else:
                # Update existing finding
                for i, ef in enumerate(merged_findings):
                    if ef["category"] == f["category"]:
                        merged_findings[i] = f
                        break

        # Append to history
        last_script = (state.get("executed_scripts") or [""])[-1]
        new_history = history + [(last_script, last_output)]

        return {
            **state,
            "scripts": [new_script],
            "findings": merged_findings,
            "phase": phase,
            "waste_beliefs": updated_beliefs,
            "output_history": new_history[-10:],
            "last_reasoning": reasoning,
        }

    except Exception as e:
        print(f"[CostMaster] Parse error: {e}\nRaw response: {raw[:500] if 'raw' in dir() else 'N/A'}")
        # Fallback: return a broad survey script
        fallback = f"""
# Fallback survey — checking all tables
import json
PROJECT_ID = os.environ["GCP_PROJECT_ID"]
DATASET = os.environ.get("BQ_DATASET", "genesis_cost")

for table in ["vm_cpu_utilization", "vm_memory_utilization",
              "cloud_run_metrics", "gcs_bucket_usage", "bq_job_history"]:
    try:
        df = bq(f"SELECT COUNT(*) as cnt FROM `{{PROJECT_ID}}.{{DATASET}}.{{table}}`")
        print(f"{{table}}: {{df.iloc[0,0]}} rows")
    except Exception as ex:
        print(f"{{table}}: ERROR {{ex}}")
"""
        return {
            **state,
            "scripts": [fallback],
            "waste_beliefs": beliefs,
        }


import re  # needed for strip in cost_master_reason