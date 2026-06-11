"""
policy_guard.py — The Policy Guard (UEBA layer).

Before the Master executes any write or destructive action, it routes
through here. The guard checks the proposed fix against the BLOCKED_ACTIONS
list in config.

If blocked:  sets awaiting_human_approval = True, surfaces reason to frontend
If approved: clears any previous block and lets the Master proceed

During the demo: trigger this deliberately with a "terminate_instance" action
to show judges the safety layer activating.
"""

from loguru import logger

from core.state import AgentState
from core.config import config


def check(state: AgentState) -> AgentState:
    proposed_fix = state.get("proposed_fix") or state.get("_worker_instruction") or ""
    logger.info(f"[PolicyGuard] Checking proposed action: {proposed_fix[:120]}")

    blocked_action = _find_blocked_action(proposed_fix)

    if blocked_action:
        reason = (
            f"Action '{blocked_action}' requires explicit human approval. "
            f"Genesis does not auto-execute destructive operations. "
            f"Approve via the dashboard to proceed."
        )
        logger.warning(f"[PolicyGuard] BLOCKED — {reason}")
        return {
            **state,
            "current_worker": "policy_guard",
            "awaiting_human_approval": True,
            "fix_blocked_reason": reason,
            "step_log": [
                f"[PolicyGuard] ⛔ BLOCKED '{blocked_action}' — human approval required"
            ],
        }

    logger.info("[PolicyGuard] ✅ Action approved for auto-execution")
    return {
        **state,
        "current_worker": "policy_guard",
        "awaiting_human_approval": False,
        "fix_blocked_reason": None,
        "step_log": ["[PolicyGuard] ✅ Action cleared — safe to auto-execute"],
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_blocked_action(text: str) -> str | None:
    """Return the first blocked action keyword found in the text, or None."""
    text_lower = text.lower()
    for action in config.BLOCKED_ACTIONS:
        # Match both underscore form and space form
        if action in text_lower or action.replace("_", " ") in text_lower:
            return action
    return None
