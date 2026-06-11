"""
engineer.py — The Engineer worker.

Receives a Python script from the Master (embedded in the instruction),
executes it inside an isolated E2B sandbox, and returns stdout/stderr.

The Engineer never decides what to run — it only runs what the Master sends.
If the script fails, the Master reads the error and rewrites before retrying.
"""

import re
import os
from e2b_code_interpreter import Sandbox
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential
from pymongo import MongoClient, InsertOne, ASCENDING
from pymongo.errors import BulkWriteError
from dotenv import load_dotenv

load_dotenv()

from core.state import AgentState
from core.config import config


def execute(state: AgentState) -> AgentState:
    instruction = state.get("_worker_instruction", "")
    logger.info(f"[Engineer] Received instruction ({len(instruction)} chars)")
 
    script = _extract_script(instruction)
    if not script:
        logger.warning("[Engineer] No Python script found in instruction")
        no_script_msg = (
            "[Engineer] ❌ No Python script found in Master instruction. "
            "The instruction field MUST contain actual code in a ```python``` block. "
            f"Instruction received was: {instruction[:200]!r}"
        )
        # Increment retry_count so the hard-stop guard eventually triggers
        scripts_executed = list(state.get("scripts_executed", []))
        scripts_executed.append({
            "script": "",
            "output": "",
            "stderr": no_script_msg,
            "success": False,
        })
        return {
            **state,
            "current_worker": "engineer",
            "scripts_executed": scripts_executed,
            "step_log": [no_script_msg],
            "retry_count": state.get("retry_count", 0) + 1,
        }
 
    # Auto-inject MongoDB header — robust against all Gemini failure modes
    script = _inject_mongodb_header(script)
 
    logger.info(f"[Engineer] Executing script ({len(script)} chars)...")
    result = _run_in_sandbox(script)
 
    execution_record = {
        "script": script,
        "output": result["output"],
        "stderr": result["stderr"],
        "success": result["success"],
    }
 
    scripts_executed = list(state.get("scripts_executed", []))
    scripts_executed.append(execution_record)
 
    status = "✅ succeeded" if result["success"] else "❌ failed"
    log_entry = (
        f"[Engineer] Script {status}. "
        f"Output preview: {result['output'][:300]}"
        + (f" | Error: {result['stderr'][:200]}" if not result["success"] else "")
    )
    logger.info(log_entry)
    
    graph_data_json = None
    for line in result["output"].split("\n"):
        if "GENESIS_GRAPH_DATA:" in line:
            try:
                import json as _json
                raw = line[line.index("GENESIS_GRAPH_DATA:") + len("GENESIS_GRAPH_DATA:"):]
                graph_data_json = _json.loads(raw)
            except Exception as e:
                logger.warning(f"[Engineer] Graph data parse error: {e}")
            break
        
    return {
        **state,
        "current_worker": "engineer",
        "scripts_executed": scripts_executed,
        "step_log": [log_entry],
        "retry_count": state.get("retry_count", 0) + (0 if result["success"] else 1),
        # Store graph data if found — server.py picks this up
        **({"graph_data": graph_data_json} if graph_data_json else {}),
    }

def _inject_mongodb_header(script: str) -> str:
    """
    If the script references MongoDB but lacks the connection boilerplate,
    prepend the full header automatically. This makes the agent robust
    regardless of how Gemini writes the script.
    """
    mongodb_signals = ["MongoClient", "pymongo", "mongodb", "MONGODB", "db[", "db."]
    needs_mongo = any(sig in script for sig in mongodb_signals)

    if not needs_mongo:
        return script  # Not a MongoDB script — leave unchanged

    has_header = (
        "subprocess.run" in script and "pymongo" in script
        and "MongoClient" in script
        and "os.getenv" in script
    )

    if has_header:
        return script  # Already has correct header — leave unchanged

    # Strip any broken partial attempts Gemini may have written
    lines = script.split("\n")
    clean_lines = []
    skip_patterns = [
        "pip install", "RUN:", "import pymongo",
        "from pymongo", "MongoClient", "load_dotenv",
        "MONGODB_URI", "MONGODB_DB", "connect_to_mongodb",
        "subprocess", "import os", "import sys",
    ]
    for line in lines:
        if any(p in line for p in skip_patterns):
            continue
        clean_lines.append(line)
    clean_script = "\n".join(clean_lines).strip()

    # Prepend the guaranteed-correct header
    header = '''import subprocess
subprocess.run(["pip", "install", "pymongo", "-q"], check=True)

import os
import sys
from pymongo import MongoClient

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB  = os.getenv("MONGODB_DB", "genesis_compliance")

try:
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    db = client[MONGODB_DB]
    print("Connected:", MONGODB_DB)
except Exception as e:
    print("CONNECTION FAILED:", e)
    sys.exit(1)

'''
    return header + clean_script

# ── Sandbox execution ─────────────────────────────────────────────────────────

@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=3))
def _run_in_sandbox(script: str) -> dict:
    """Run script in an isolated E2B sandbox. Returns stdout, stderr, success flag."""
    try:
        with Sandbox(api_key=config.E2B_API_KEY) as sandbox:
            execution = sandbox.run_code(script, envs={"MONGODB_URI": os.getenv("MONGODB_URI"),"MONGODB_DB":  os.getenv("MONGODB_DB", "genesis_compliance"),})
            stdout = "\n".join(str(line) for line in (execution.logs.stdout or []))
            stderr = "\n".join(str(line) for line in (execution.logs.stderr or []))
            success = execution.error is None
            if not success:
                stderr = str(execution.error) + "\n" + stderr
            return {"output": stdout, "stderr": stderr, "success": success}
    except Exception as exc:
        logger.error(f"[Engineer] Sandbox error: {exc}")
        return {"output": "", "stderr": str(exc), "success": False}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_script(instruction: str) -> str:
    """
    Pull Python code out of the Master's instruction.
    Handles multiple formats the LLM might produce.
    """
    # 1. Explicit ```python fence (most common)
    match = re.search(r'```python\s*\n(.*?)```', instruction, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 2. Any ``` fence
    match = re.search(r'```\s*\n(.*?)```', instruction, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 3. Inline ``` without newline after opening fence
    match = re.search(r'```python(.*?)```', instruction, re.DOTALL)
    if match:
        return match.group(1).strip()

    match = re.search(r'```(.*?)```', instruction, re.DOTALL)
    if match:
        candidate = match.group(1).strip()
        if len(candidate) > 10:
            return candidate

    # 4. Starts with common Python patterns
    stripped = instruction.strip()
    python_starters = (
        "import ", "from ", "def ", "class ", "#", "print(",
        "with ", "try:", "for ", "while ", "if ",
        "open(", "boto3", "os.", "json.", "requests.",
    )
    if stripped.startswith(python_starters):
        return stripped

    # 5. Contains Python keywords strongly suggesting it IS a script
    # even if the LLM forgot to wrap it in fences
    python_signals = ["import ", "def ", "print(", "open(", "with open", "os.path"]
    lines = stripped.split("\n")
    if any(any(sig in line for sig in python_signals) for line in lines):
        # Filter out obvious prose lines (long sentences ending in punctuation)
        code_lines = [
            l for l in lines
            if not (len(l) > 120 and l.rstrip().endswith((".","!","?")))
        ]
        candidate = "\n".join(code_lines).strip()
        if candidate:
            return candidate

    return ""
