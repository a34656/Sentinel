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
    Handles:
    - ```python\\n...``` fenced blocks
    - ``` ... ``` plain fenced blocks
    - Raw Python (no fences)
    """
    # Prefer explicit python fence
    match = re.search(r'```python\s*\n(.*?)```', instruction, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Fall back to any fenced block
    match = re.search(r'```\s*\n(.*?)```', instruction, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Treat the whole instruction as a script if it looks like Python
    stripped = instruction.strip()
    if stripped.startswith(("import ", "from ", "def ", "#", "boto3", "print")):
        return stripped

    return ""
