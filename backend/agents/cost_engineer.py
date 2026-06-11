"""
agents/cost_engineer.py
-----------------------
Like engineer.py in Genesis but for GCP cost analysis.
- Strips any MongoDB/shell patterns Gemini might hallucinate
- Injects a mandatory BigQuery connection header before every E2B execution
- Passes GCP_PROJECT_ID and BQ_DATASET as env vars into the sandbox
"""

import os
import re
import json
import asyncio
from e2b_code_interpreter import Sandbox
from core.cost_state import CostAgentState

# ── BigQuery boilerplate injected at the top of every script ─────────────────

BQ_HEADER = '''
import os
import json
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT_ID = os.environ["GCP_PROJECT_ID"]
DATASET    = os.environ.get("BQ_DATASET", "genesis_cost")

_key_json = os.environ.get("GCP_SA_KEY_JSON", "")
if _key_json:
    _creds = service_account.Credentials.from_service_account_info(
        json.loads(_key_json),
        scopes=["https://www.googleapis.com/auth/bigquery"]
    )
    client = bigquery.Client(project=PROJECT_ID, credentials=_creds)
else:
    client = bigquery.Client(project=PROJECT_ID)

def bq(sql: str) -> pd.DataFrame:
    """Run a BigQuery SQL query and return a DataFrame."""
    return client.query(sql).to_dataframe()

print(f"Connected: {PROJECT_ID}.{DATASET}")
'''

# Patterns that indicate Gemini hallucinated MongoDB or shell code
BAD_PATTERNS = [
    r"pymongo",
    r"MongoClient",
    r"mongodb\+srv://",
    r"genesis_compliance",
    r"subprocess\.run",
    r"import subprocess",
    r"os\.system",
    r"from dotenv",
    r"load_dotenv",
    r"boto3",           # wrong cloud SDK
    r"import sqlite3",
]

def _strip_bad_patterns(script: str) -> str:
    """Remove any lines containing bad patterns."""
    lines = script.split("\n")
    clean = []
    for line in lines:
        skip = False
        for pat in BAD_PATTERNS:
            if re.search(pat, line, re.IGNORECASE):
                skip = True
                break
        if not skip:
            clean.append(line)
    return "\n".join(clean)

def _strip_existing_bq_setup(script: str) -> str:
    """Remove duplicate BigQuery client setup the model might include."""
    remove_blocks = [
        r"from google\.cloud import bigquery.*?\n",
        r"from google\.oauth2.*?\n",
        r"client\s*=\s*bigquery\.Client.*?\n",
        r"PROJECT_ID\s*=.*?\n",
        r"DATASET\s*=.*?\n",
    ]
    for pat in remove_blocks:
        script = re.sub(pat, "", script)
    return script

def _inject_bq_header(script: str) -> str:
    """Strip bad patterns and prepend the correct BQ header."""
    script = _strip_bad_patterns(script)
    script = _strip_existing_bq_setup(script)
    # Remove markdown code fences if Gemini wrapped the script
    script = re.sub(r"^```python\s*", "", script, flags=re.MULTILINE)
    script = re.sub(r"^```\s*$", "", script, flags=re.MULTILINE)
    return BQ_HEADER + "\n# ── agent script ──────────────────────────────────\n" + script.strip()

async def execute_cost_script(state: CostAgentState) -> CostAgentState:
    """
    Execute the latest script from state in an E2B sandbox.
    Injects BigQuery credentials automatically.
    """
    scripts = state.get("scripts", [])
    if not scripts:
        return {**state, "last_output": "ERROR: No script to execute"}

    raw_script = scripts[-1]
    final_script = _inject_bq_header(raw_script)

    # Build env vars for the sandbox
    envs = {
        "GCP_PROJECT_ID":   os.environ["GCP_PROJECT_ID"],
        "BQ_DATASET":       os.environ.get("BQ_DATASET", "genesis_cost"),
        "GCP_SA_KEY_JSON":  os.environ.get("GCP_SA_KEY_JSON", ""),
    }

    iteration = state.get("iteration", 0)
    print(f"\n[CostEngineer] Executing script (iteration {iteration})")
    print(f"[CostEngineer] Script preview:\n{final_script[:300]}...\n")

    try:
        with Sandbox(timeout=120) as sandbox:
            execution = sandbox.run_code(final_script, envs=envs)

            stdout_parts = []
            stderr_parts = []

            for log in execution.logs.stdout:
                stdout_parts.append(str(log))
            for log in execution.logs.stderr:
                stderr_parts.append(str(log))

            output = "\n".join(stdout_parts)
            errors = "\n".join(stderr_parts)

            if execution.error:
                error_msg = f"ERROR: {execution.error.name}: {execution.error.value}"
                if execution.error.traceback:
                    error_msg += f"\nTraceback:\n{execution.error.traceback[-2000:]}"
                combined = f"{output}\n{error_msg}" if output else error_msg
            else:
                combined = output
                if errors:
                    combined += f"\n[STDERR]\n{errors}"

            # Truncate to avoid overwhelming Gemini context
            if len(combined) > 8000:
                combined = combined[:4000] + "\n...[truncated]...\n" + combined[-2000:]

            print(f"[CostEngineer] Output ({len(combined)} chars):\n{combined[:500]}")

            return {
                **state,
                "last_output": combined,
                "executed_scripts": state.get("executed_scripts", []) + [final_script],
                "iteration": iteration + 1,
            }

    except Exception as e:
        error = f"SANDBOX_ERROR: {type(e).__name__}: {str(e)}"
        print(f"[CostEngineer] {error}")
        return {
            **state,
            "last_output": error,
            "iteration": iteration + 1,
        }