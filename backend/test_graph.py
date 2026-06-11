from core.graph import genesis_graph
import asyncio
from core.state import AgentState

async def run():
    initial_state: AgentState = {
        "messages": [],
        "incident_prompt": "test",
        "incident_id": "123",
        "root_cause": None,
        "confidence_score": 0.0,
        "corroborating_signals": [],
        "raw_logs": None,
        "raw_cost_data": {},
        "documentation_context": None,
        "prior_incidents": [],
        "scripts_written": [],
        "scripts_executed": [],
        "retry_count": 0,
        "proposed_fix": None,
        "fix_applied": False,
        "fix_blocked_reason": None,
        "awaiting_human_approval": False,
        "final_report_path": None,
        "notion_page_url": None,
        "should_terminate": False,
        "current_worker": "initializing",
        "step_log": [],
        "_next_worker": "",
        "_worker_instruction": "",
    }
    try:
        async for step in genesis_graph.astream(initial_state):
            print("STEP:", step.keys())
    except Exception as e:
        print("ERROR TYPE:", type(e))
        print("ERROR MESSAGE:", str(e))
        import traceback
        traceback.print_exc()

asyncio.run(run())
