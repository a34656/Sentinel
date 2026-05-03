"""
Genesis Master Orchestrator Agent
==================================
The brain. Reasons, decides, delegates — never executes directly.
Built on LangGraph for stateful multi-step loops.
Uses Gemini 1.5 Pro via Vertex AI Reasoning Engine.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, TypedDict

import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_vertexai import ChatVertexAI
from langgraph.graph import END, StateGraph, add_messages
from langgraph.prebuilt import ToolNode
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.tools.e2b_tool import execute_python_in_sandbox
from backend.tools.firecrawl_tool import crawl_documentation
from backend.tools.gcp_tool import fetch_cloud_logs
from backend.tools.aws_tool import fetch_aws_billing
from backend.tools.notion_tool import read_runbook, write_post_mortem
from backend.tools.memory_tool import query_memory, store_memory
from backend.policy.guard import PolicyGuard

logger = structlog.get_logger(__name__)

# ── Agent State ────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    """
    The full state object passed between every node in the LangGraph.
    Persisted to PostgreSQL at each step for checkpoint/resume.
    """
    run_id: str
    incident_prompt: str
    messages: Annotated[list[BaseMessage], add_messages]
    confidence_score: float          # 0.0 – 1.0, updated as evidence accumulates
    root_cause: str | None
    fix_applied: str | None
    cost_impact: str | None
    timeline: list[dict]             # [{timestamp, event, worker, result}]
    blocked_actions: list[dict]      # Actions blocked by PolicyGuard
    awaiting_human_approval: bool
    status: Literal[
        "running", "resolved", "blocked", "failed", "awaiting_approval"
    ]
    final_report_path: str | None
    notion_page_url: str | None


# ── Tool Registry ──────────────────────────────────────────────────────────────

ALL_TOOLS = [
    execute_python_in_sandbox,   # Worker 2 — The Engineer (E2B)
    crawl_documentation,         # Worker 1 — The Scout (Firecrawl)
    fetch_cloud_logs,            # Worker 3 — The Analyst (GCP)
    fetch_aws_billing,           # Worker 3 — The Analyst (AWS)
    read_runbook,                # Worker 4 — The Scribe (read)
    write_post_mortem,           # Worker 4 — The Scribe (write)
    query_memory,                # Worker 7 — Memory Agent
    store_memory,                # Worker 7 — Memory Agent
]

TOOL_NODE = ToolNode(ALL_TOOLS)

# ── LLM Setup ─────────────────────────────────────────────────────────────────

def build_llm() -> ChatVertexAI:
    """
    Gemini 1.5 Pro via Vertex AI.
    1M token context window holds full logs + code + memory simultaneously.
    """
    return ChatVertexAI(
        model_name="gemini-1.5-pro",
        temperature=0.1,          # Low temp for deterministic debugging logic
        max_output_tokens=8192,
        streaming=True,
    ).bind_tools(ALL_TOOLS)


# ── System Prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Genesis Orchestrator, an autonomous SRE incident response agent.

Your role: REASON and DELEGATE. You never execute code directly — you call workers.

WORKERS AVAILABLE:
- execute_python_in_sandbox: Run Python code safely via E2B. Use for data analysis, API calls, log parsing.
- crawl_documentation: Read live documentation URLs via Firecrawl when you encounter unfamiliar APIs.
- fetch_cloud_logs: Pull GCP Cloud Logging data for a service and time range.
- fetch_aws_billing: Pull AWS Cost Explorer data for billing anomalies.
- read_runbook: Read internal Notion runbooks for this service type.
- write_post_mortem: Publish formatted post-mortem to Notion (only call after resolution).
- query_memory: Check if a similar incident was seen before. ALWAYS call this first.
- store_memory: After resolution, save root cause + fix for future incidents.

OPERATING RULES:
1. ALWAYS call query_memory first. Prior incidents save investigation time.
2. Build confidence incrementally. State your current confidence (0-100%) after each worker result.
3. When you write code for execute_python_in_sandbox, write complete, runnable Python scripts.
4. If a script fails, read the error, fix the code, and retry. Max 3 retries per script.
5. NEVER take destructive actions (terminate instance, delete resource, modify config) without stating explicitly that you need PolicyGuard approval. Format: "POLICY_CHECK_REQUIRED: <action_description>"
6. When confidence reaches 80%+, synthesise findings and call write_post_mortem.
7. Be specific. "High CPU on instance i-abc123" not "there was an issue".

CONFIDENCE SCORING:
- +20% per independent corroborating data source
- +15% if memory returns a matching prior incident
- -10% for each contradicting signal
- Report as: "CONFIDENCE: X%"

Current timestamp: {current_time}
Run ID: {run_id}
"""


# ── Graph Nodes ────────────────────────────────────────────────────────────────

def orchestrator_node(state: AgentState) -> dict:
    """The Master Agent — one reasoning step."""
    
    llm = build_llm()
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("placeholder", "{messages}"),
    ])
    
    chain = prompt | llm
    
    response = chain.invoke({
        "messages": state["messages"],
        "current_time": datetime.utcnow().isoformat(),
        "run_id": state["run_id"],
    })
    
    # Parse confidence score from response
    confidence = _extract_confidence(response.content)
    
    # Log every step
    logger.info(
        "orchestrator_step",
        run_id=state["run_id"],
        confidence=confidence,
        tool_calls=len(response.tool_calls) if hasattr(response, "tool_calls") else 0,
    )
    
    updates: dict[str, Any] = {
        "messages": [response],
        "confidence_score": confidence or state["confidence_score"],
    }
    
    # Check for policy check signals
    if "POLICY_CHECK_REQUIRED:" in str(response.content):
        action = _extract_policy_action(response.content)
        updates["blocked_actions"] = state.get("blocked_actions", []) + [{
            "action": action,
            "timestamp": datetime.utcnow().isoformat(),
            "status": "pending_approval",
        }]
        updates["awaiting_human_approval"] = True
        updates["status"] = "awaiting_approval"
    
    return updates


def policy_guard_node(state: AgentState) -> dict:
    """
    Worker 6 — PolicyGuard.
    Checks proposed actions against authorisation table.
    Blocks and surfaces human approval requests.
    """
    guard = PolicyGuard()
    
    blocked = state.get("blocked_actions", [])
    if not blocked:
        return {}
    
    latest = blocked[-1]
    result = guard.check(latest["action"])
    
    if result.allowed:
        logger.info("policy_guard_allowed", action=latest["action"])
        updated = blocked.copy()
        updated[-1]["status"] = "approved_by_policy"
        return {
            "blocked_actions": updated,
            "awaiting_human_approval": False,
            "status": "running",
        }
    else:
        logger.warning("policy_guard_blocked", action=latest["action"], reason=result.reason)
        updated = blocked.copy()
        updated[-1]["status"] = "blocked"
        updated[-1]["reason"] = result.reason
        return {
            "blocked_actions": updated,
            "awaiting_human_approval": True,
            "status": "awaiting_approval",
        }


def should_continue(state: AgentState) -> Literal["tools", "policy_guard", "end"]:
    """Route from orchestrator: tools → policy → end."""
    
    if state.get("awaiting_human_approval"):
        return "policy_guard"
    
    last_message = state["messages"][-1]
    
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    
    # If confidence is high enough and we have a root cause, we're done
    if state["confidence_score"] >= 0.8 and state.get("root_cause"):
        return "end"
    
    return "end"


# ── Graph Assembly ─────────────────────────────────────────────────────────────

def build_genesis_graph() -> Any:
    """
    Compile the full LangGraph state machine.
    
    Flow:
    orchestrator → should_continue?
      ├── tools → TOOL_NODE → orchestrator (loop)
      ├── policy_guard → orchestrator (loop)
      └── end
    """
    
    graph = StateGraph(AgentState)
    
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("tools", TOOL_NODE)
    graph.add_node("policy_guard", policy_guard_node)
    
    graph.set_entry_point("orchestrator")
    
    graph.add_conditional_edges(
        "orchestrator",
        should_continue,
        {
            "tools": "tools",
            "policy_guard": "policy_guard",
            "end": END,
        }
    )
    
    graph.add_edge("tools", "orchestrator")
    graph.add_edge("policy_guard", "orchestrator")
    
    return graph.compile()


# ── Public Entry Point ─────────────────────────────────────────────────────────

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=10))
async def run_incident_investigation(
    incident_prompt: str,
    run_id: str | None = None,
) -> AgentState:
    """
    Public function called by the FastAPI endpoint.
    Runs the full agent graph and returns final state.
    """
    
    run_id = run_id or str(uuid.uuid4())
    
    logger.info("incident_investigation_started", run_id=run_id, prompt=incident_prompt[:100])
    
    initial_state: AgentState = {
        "run_id": run_id,
        "incident_prompt": incident_prompt,
        "messages": [HumanMessage(content=incident_prompt)],
        "confidence_score": 0.0,
        "root_cause": None,
        "fix_applied": None,
        "cost_impact": None,
        "timeline": [],
        "blocked_actions": [],
        "awaiting_human_approval": False,
        "status": "running",
        "final_report_path": None,
        "notion_page_url": None,
    }
    
    graph = build_genesis_graph()
    
    final_state = await graph.ainvoke(initial_state)
    
    logger.info(
        "incident_investigation_complete",
        run_id=run_id,
        status=final_state["status"],
        confidence=final_state["confidence_score"],
    )
    
    return final_state


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_confidence(content: str) -> float | None:
    """Parse 'CONFIDENCE: 75%' from model output."""
    import re
    match = re.search(r"CONFIDENCE:\s*(\d+)%", str(content))
    if match:
        return int(match.group(1)) / 100.0
    return None


def _extract_policy_action(content: str) -> str:
    """Parse 'POLICY_CHECK_REQUIRED: <action>' from model output."""
    import re
    match = re.search(r"POLICY_CHECK_REQUIRED:\s*(.+?)(?:\n|$)", str(content))
    if match:
        return match.group(1).strip()
    return "unknown_action"
