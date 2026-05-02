"""
graph.py — Wires all agent nodes into a LangGraph StateGraph.

Flow:
  memory_lookup → scribe_read → master → [scout | engineer | analyst
                                           | policy_guard | report_generator]
                                        → (loop back to master)
  report_generator → scribe_write → memory_store → END
"""

from langgraph.graph import StateGraph, END

from core.state import AgentState
from agents import (
    master,
    scout,
    engineer,
    analyst,
    scribe,
    report_generator,
    policy_guard,
    memory_agent,
)


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # ── Register nodes ────────────────────────────────────────────────────
    graph.add_node("memory_lookup",     memory_agent.lookup)
    graph.add_node("scribe_read",       scribe.read_runbooks)
    graph.add_node("master",            master.reason)
    graph.add_node("scout",             scout.crawl)
    graph.add_node("engineer",          engineer.execute)
    graph.add_node("analyst",           analyst.pull_data)
    graph.add_node("policy_guard",      policy_guard.check)
    graph.add_node("report_generator",  report_generator.generate)
    graph.add_node("scribe_write",      scribe.publish_report)
    graph.add_node("memory_store",      memory_agent.store)

    # ── Entry point ───────────────────────────────────────────────────────
    graph.set_entry_point("memory_lookup")

    # ── Fixed edges ───────────────────────────────────────────────────────
    graph.add_edge("memory_lookup",    "scribe_read")
    graph.add_edge("scribe_read",      "master")

    # Workers return to master (which decides what to do with the output)
    graph.add_edge("scout",            "master")
    graph.add_edge("engineer",         "master")
    graph.add_edge("analyst",          "master")
    graph.add_edge("policy_guard",     "master")

    # Report pipeline: generate → publish to Notion → store in memory → done
    graph.add_edge("report_generator", "scribe_write")
    graph.add_edge("scribe_write",     "memory_store")
    graph.add_edge("memory_store",     END)

    # ── Conditional routing from master ───────────────────────────────────
    graph.add_conditional_edges(
        "master",
        master.route_next,
        {
            "scout":            "scout",
            "engineer":         "engineer",
            "analyst":          "analyst",
            "policy_guard":     "policy_guard",
            "report":           "report_generator",
            "end":              END,
        },
    )

    return graph.compile()


# Module-level singleton — import this everywhere
genesis_graph = build_graph()
