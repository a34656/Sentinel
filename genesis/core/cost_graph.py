"""
core/cost_graph.py
------------------
LangGraph orchestration for the Cloud Cost Optimization agent.
Graph mirrors Genesis's core/graph.py structure.

Nodes:
  master  → Gemini reasons, writes next script
  engineer → E2B executes script
  reporter → generates PDF post-mortem

Edges:
  master → engineer (always — execute what master wrote)
  engineer → master (if not complete and under retry limit)
  engineer → reporter (if complete OR max retries hit)
"""

import os
from langgraph.graph import StateGraph, END
from core.cost_state import CostAgentState
from agents.cost_master import cost_master_reason, MAX_SCRIPT_RETRIES
from agents.cost_engineer import execute_cost_script
from agents.cost_reporter import generate_cost_report

MAX_ITERATIONS = MAX_SCRIPT_RETRIES + 2  # schema inspection + retries


def should_continue(state: CostAgentState) -> str:
    """Route after engineer executes: continue investigating or write report."""
    iteration = state.get("iteration", 0)
    phase     = state.get("phase", "investigating")

    if phase == "complete":
        print(f"[CostGraph] Phase=complete after {iteration} iterations → reporter")
        return "reporter"

    if iteration >= MAX_ITERATIONS:
        print(f"[CostGraph] Max iterations ({MAX_ITERATIONS}) reached → reporter")
        return "reporter"

    # Check if we have high confidence on all 5 categories
    beliefs = state.get("waste_beliefs", {})
    if beliefs and all(v >= 0.80 for v in beliefs.values()):
        print(f"[CostGraph] All beliefs ≥ 80% → reporter")
        return "reporter"

    return "master"


def build_cost_graph():
    graph = StateGraph(CostAgentState)

    graph.add_node("master",   cost_master_reason)
    graph.add_node("engineer", execute_cost_script)
    graph.add_node("reporter", generate_cost_report)

    graph.set_entry_point("master")

    graph.add_edge("master", "engineer")

    graph.add_conditional_edges(
        "engineer",
        should_continue,
        {
            "master":   "master",
            "reporter": "reporter",
        }
    )

    graph.add_edge("reporter", END)

    return graph.compile()


cost_app = build_cost_graph()