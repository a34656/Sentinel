"""
engineer.py — The Engineer worker.

Receives a Python script from the Master (embedded in the instruction),
executes it inside an isolated E2B sandbox, and returns stdout/stderr.

The Engineer never decides what to run — it only runs what the Master sends.
If the script fails, the Master reads the error and rewrites before retrying.
"""

import re

from e2b_code_interpreter import Sandbox
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from core.state import AgentState
from core.config import config


def execute(state: AgentState) -> AgentState:
    instruction = state.get("_worker_instruction", "")
    logger.info(f"[Engineer] Received instruction ({len(instruction)} chars)")

    script = _extract_script(instruction)
    if not script:
        logger.warning("[Engineer] No Python script found in instruction")
        return {
            **state,
            "current_worker": "engineer",
            "step_log": ["[Engineer] ⚠️  No script found in Master instruction — skipping execution"],
        }

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

    return {
        **state,
        "current_worker": "engineer",
        "scripts_executed": scripts_executed,
        "step_log": [log_entry],
        # Increment retry_count only on failure so Master knows how many attempts remain
        "retry_count": state.get("retry_count", 0) + (0 if result["success"] else 1),
    }


# ── Sandbox execution ─────────────────────────────────────────────────────────

@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=3))
def _run_in_sandbox(script: str) -> dict:
    """Run script in an isolated E2B sandbox. Returns stdout, stderr, success flag."""
    try:
        with Sandbox(api_key=config.E2B_API_KEY) as sandbox:
            execution = sandbox.run_code(script)
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
