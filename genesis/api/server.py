"""
server.py — FastAPI backend for Genesis SRE Agent.
Patched: added GET /api/incidents, GET /health with version,
         fixed CORS to accept any localhost port during dev.
"""

import json
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from loguru import logger

from core.graph import genesis_graph
from core.state import AgentState
from core.config import config


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Genesis API starting up")
    try:
        from tools.obsidian_sync import sync_vault_to_db
        synced = sync_vault_to_db()
        if synced:
            logger.info(f"[Startup] Obsidian: synced {synced} vault notes")
    except Exception as exc:
        logger.debug(f"[Startup] Obsidian sync skipped: {exc}")

    if config.WATCHDOG_ENABLED:
        from api.watchdog_routes import start_watchdog_scheduler
        await start_watchdog_scheduler()
        logger.info("[Startup] Watchdog scheduler started")

    yield
    logger.info("Genesis API shutting down")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Genesis SRE Agent API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # Accept any localhost/127.0.0.1 port during development
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.watchdog_routes import router as watchdog_router
from api.planner_routes import router as planner_router
app.include_router(watchdog_router)
app.include_router(planner_router)

# incident_id → should_continue
active_runs: dict[str, bool] = {}


# ── Models ────────────────────────────────────────────────────────────────────

class IncidentRequest(BaseModel):
    prompt: str


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/api/incident")
async def start_incident(req: IncidentRequest):
    """
    Start a new incident investigation.
    Returns text/event-stream of JSON events.

    SSE event types (exactly as frontend expects):
      { type: "init",     incident_id }
      { type: "step",     current_worker, step_log, confidence_score,
                          bayesian_beliefs, bayesian_entropy, bayesian_top_cause,
                          root_cause, awaiting_human_approval, fix_blocked_reason,
                          notion_page_url, final_report_path }
      { type: "complete", incident_id, root_cause, notion_page_url }
      { type: "killed" }
      { type: "error",    message }
    """
    incident_id = str(uuid.uuid4())
    active_runs[incident_id] = True
    logger.info(f"[API] Starting incident {incident_id}: {req.prompt[:80]}")

    initial_state: AgentState = {
        "messages": [],
        "incident_prompt": req.prompt,
        "incident_id": incident_id,
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
        "memory_context": None,
        "bayesian_beliefs": {},
        "bayesian_entropy": 0.0,
        "bayesian_top_cause": None,
        "bayesian_suggestion": None,
        "obsidian_context": None,
        "schema_context": None,
    }

    # Track final state values for the complete event
    final: dict = {"root_cause": None, "notion_page_url": None}

    async def stream():
        try:
            yield _sse("init", {"incident_id": incident_id})

            async for step in genesis_graph.astream(initial_state, config={"recursion_limit": 100}, stream_mode="updates"):
                if not active_runs.get(incident_id, False):
                    yield _sse("killed", {"incident_id": incident_id})
                    return

                for node_name, state_update in step.items():
                    # Track final values as they arrive
                    if state_update.get("graph_data"):
                        yield _sse("graph_data", {
                            "incident_id": incident_id,
                            **state_update["graph_data"],
                        })

                    event = {
                        "node":                    node_name,
                        "step_log":                state_update.get("step_log", []),
                        "confidence_score":        state_update.get("confidence_score", 0.0),
                        "current_worker":          state_update.get("current_worker", ""),
                        "root_cause":              state_update.get("root_cause"),
                        "awaiting_human_approval": state_update.get("awaiting_human_approval", False),
                        "fix_blocked_reason":      state_update.get("fix_blocked_reason"),
                        "notion_page_url":         state_update.get("notion_page_url"),
                        "final_report_path":       state_update.get("final_report_path"),
                        "bayesian_entropy":        state_update.get("bayesian_entropy", 0.0),
                        "bayesian_top_cause":      state_update.get("bayesian_top_cause"),
                        "bayesian_beliefs":        state_update.get("bayesian_beliefs", {}),
                    }
                    yield _sse("step", event)

            # Send complete with the accumulated final values
            yield _sse("complete", {
                "incident_id":   incident_id,
                "root_cause":    final["root_cause"],
                "notion_page_url": final["notion_page_url"],
            })

        except Exception as exc:
            logger.error(f"[API] Stream error for {incident_id}: {exc}")
            yield _sse("error", {"message": str(exc)})
        finally:
            active_runs.pop(incident_id, None)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.post("/api/incident/{incident_id}/kill")
async def kill_incident(incident_id: str):
    if incident_id not in active_runs:
        raise HTTPException(status_code=404, detail="Incident not found or already complete")
    active_runs[incident_id] = False
    logger.warning(f"[API] Kill switch activated for {incident_id}")
    return {"killed": True, "incident_id": incident_id}


@app.post("/api/incident/{incident_id}/approve")
async def approve_action(incident_id: str):
    logger.info(f"[API] Human approval received for {incident_id}")
    return {"approved": True, "incident_id": incident_id}


@app.get("/api/incidents")
async def list_incidents(limit: int = 20):
    """
    Return past incidents from Supabase incident_memory table.
    Frontend uses this for the Incident History panel.
    """
    try:
        from supabase import create_client
        client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
        result = (
            client.table("incident_memory")
            .select("incident_id, incident_prompt, root_cause, confidence_score, notion_url, created_at, fix_applied")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        # Normalize to what the frontend IncidentHistory component expects
        incidents = [
            {
                "incident_id":  row.get("incident_id"),
                "prompt":       row.get("incident_prompt", ""),
                "status":       "complete" if row.get("fix_applied") else "complete",
                "confidence":   row.get("confidence_score", 0.0),
                "root_cause":   row.get("root_cause"),
                "notion_url":   row.get("notion_url"),
                "started_at":   row.get("created_at", ""),
            }
            for row in (result.data or [])
        ]
        return {"incidents": incidents, "count": len(incidents)}
    except Exception as exc:
        logger.error(f"[API] list_incidents failed: {exc}")
        # Return empty list — don't crash the frontend
        return {"incidents": [], "count": 0, "error": str(exc)}


@app.get("/health")
async def health():
    return {
        "status":  "ok",
        "version": "1.0.0",
        "active_runs": len(active_runs),
    }


# ── Helper ────────────────────────────────────────────────────────────────────

def _sse(event_type: str, data: dict) -> str:
    payload = json.dumps({"type": event_type, **data})
    return f"data: {payload}\n\n"
