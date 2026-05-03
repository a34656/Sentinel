"""
AgentState — the single shared state object that flows through the LangGraph.

Every worker receives the full state and returns an updated copy.
Only the keys a worker touches need to be returned; LangGraph merges the rest.
"""

from typing import TypedDict, Annotated, Sequence, Optional
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage
import operator


class AgentState(TypedDict):
    # ── Core conversation ─────────────────────────────────────────────────
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # ── Incident identity ─────────────────────────────────────────────────
    incident_prompt: str
    incident_id: str

    # ── Investigation state ───────────────────────────────────────────────
    root_cause: Optional[str]
    confidence_score: float           # 0.0 → 1.0
    corroborating_signals: list[str]

    # ── Data collected by workers ─────────────────────────────────────────
    raw_logs: Optional[str]
    raw_cost_data: Optional[dict]
    documentation_context: Optional[str]
    prior_incidents: list[dict]       # From memory lookup at start

    # ── Execution tracking ────────────────────────────────────────────────
    scripts_written: list[str]
    scripts_executed: list[dict]      # [{script, output, stderr, success}]
    retry_count: int

    # ── Actions ───────────────────────────────────────────────────────────
    proposed_fix: Optional[str]
    fix_applied: bool
    fix_blocked_reason: Optional[str]   # Set by PolicyGuard when blocked
    awaiting_human_approval: bool

    # ── Final output ──────────────────────────────────────────────────────
    final_report_path: Optional[str]
    notion_page_url: Optional[str]

    # ── Control flow ──────────────────────────────────────────────────────
    should_terminate: bool            # Kill switch sets this True
    current_worker: str               # Streamed to frontend in real time
    step_log: Annotated[list[str], operator.add]  # Append-only across steps

    # ── Internal routing (not streamed to frontend) ───────────────────────
    _next_worker: str
    _worker_instruction: str

    # ── Three-tier memory context (injected at investigation start) ────────
    # Layer 3 rules + Layer 2 similar episodes, pre-formatted for Master context.
    # Flat string, ~1300 tokens regardless of system uptime.
    memory_context: Optional[str]

    # ── Bayesian investigation state ───────────────────────────────────────
    # Serialised BeliefState from tools/bayesian_selector.py.
    # Stored as dict so it survives LangGraph state serialisation.
    bayesian_beliefs: Optional[dict]         # {cause: probability}
    bayesian_entropy: float                   # current belief entropy
    bayesian_top_cause: Optional[str]        # leading hypothesis from Bayesian model
    bayesian_suggestion: Optional[str]       # formatted hint injected into Master context

    # ── Obsidian context (human corrections + relevant vault notes) ────────
    obsidian_context: Optional[str]
