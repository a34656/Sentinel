"""
Worker 2 — The Engineer
========================
Executes Python scripts in E2B's secure isolated sandbox.
Captures stdout, stderr, and returns full output to the Orchestrator.
The Engineer NEVER decides what to run — only runs what the Master sends.
"""

from __future__ import annotations

import os
from typing import Any

import structlog
from e2b_code_interpreter import CodeInterpreter
from langchain_core.tools import tool
from tenacity import retry, stop_after_attempt, wait_fixed

logger = structlog.get_logger(__name__)

MAX_RETRIES = 3
SANDBOX_TIMEOUT_SECONDS = 60


@tool
def execute_python_in_sandbox(
    script: str,
    description: str = "",
) -> dict[str, Any]:
    """
    Execute a Python script in a secure E2B sandbox.
    
    Use this to:
    - Run boto3 scripts to call AWS Cost Explorer API
    - Process and parse log files
    - Run data transformation and analysis
    - Call any external API via Python

    Args:
        script: Complete, runnable Python script. Include all imports.
        description: One-sentence description of what this script does (for logging).

    Returns:
        Dict with 'stdout', 'stderr', 'success' (bool), 'error' (str if failed).
    """
    
    api_key = os.environ["E2B_API_KEY"]
    
    logger.info("sandbox_execution_start", description=description, script_length=len(script))
    
    try:
        with CodeInterpreter(api_key=api_key, timeout=SANDBOX_TIMEOUT_SECONDS) as sandbox:
            execution = sandbox.notebook.exec_cell(script)
            
            stdout = "\n".join([
                str(line) for line in execution.logs.stdout
            ])
            stderr = "\n".join([
                str(line) for line in execution.logs.stderr
            ])
            
            success = execution.error is None
            
            result = {
                "success": success,
                "stdout": stdout,
                "stderr": stderr,
                "error": str(execution.error) if execution.error else None,
                "description": description,
            }
            
            if success:
                logger.info("sandbox_execution_success", description=description)
            else:
                logger.warning(
                    "sandbox_execution_failed",
                    description=description,
                    error=result["error"],
                )
            
            return result
            
    except Exception as e:
        logger.error("sandbox_execution_exception", error=str(e))
        return {
            "success": False,
            "stdout": "",
            "stderr": "",
            "error": f"Sandbox error: {str(e)}",
            "description": description,
        }
