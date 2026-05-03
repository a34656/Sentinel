"""
server.py — FastAPI backend.

Endpoints:
  POST /api/incident          → Start a new incident investigation (returns SSE stream)
  POST /api/incident/{id}/kill    → Kill switch — stop a running investigation
  POST /api/incident/{id}/approve → Human approval for a blocked action

The SSE stream emits JSON events for every agent step so the Next.js
frontend can update the live feed, confidence meter, and UEBA panel in real time.
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


# ── App setup ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Genesis API starting up")

    # Sync Obsidian vault index on startup (non-blocking)
    try:
        from tools.obsidian_sync import sync_vault_to_db
        synced = sync_vault_to_db()
        if synced:
            logger.info(f"[Startup] Obsidian: synced {synced} vault notes")
    except Exception as exc:
        logger.debug(f"[Startup] Obsidian sync skipped: {exc}")

    # Start watchdog if enabled
    if config.WATCHDOG_ENABLED:
        from api.watchdog_routes import start_watchdog_scheduler
        await start_watchdog_scheduler()
        logger.info("[Startup] Watchdog scheduler started")

    yield

    logger.info("Genesis API shutting down")


app = FastAPI(title="Genesis SRE Agent API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount watchdog routes
from api.watchdog_routes import router as watchdog_router
app.include_router(watchdog_router)

# Track active runs: incident_id → should_continue (bool)
active_runs: dict[str, bool] = {}


# ── Request models ────────────────────────────────────────────────────────────

class IncidentRequest(BaseModel):
    prompt: str


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/api/incident")
async def start_incident(req: IncidentRequest):
    """
    Start a new incident investigation.
    Returns a text/event-stream of JSON events.

    Event types:
      step      → one agent step completed (streamed continuously)
      complete  → investigation finished
      error     → unhandled exception
      terminated → killed by user
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
        # Three-tier memory (populated by memory_lookup node)
        "memory_context": None,
        "bayesian_beliefs": {},
        "bayesian_entropy": 0.0,
        "bayesian_top_cause": None,
        "bayesian_suggestion": None,
        "obsidian_context": None,
    }

    async def stream():
        try:
            # Send the incident_id immediately so the frontend can wire up kill switch
            yield _sse("init", {"incident_id": incident_id})

            async for step in genesis_graph.astream(initial_state):
                # Kill switch check
                if not active_runs.get(incident_id, False):
                    yield _sse("terminated", {"message": "Stopped by user"})
                    break

                for node_name, state_update in step.items():
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
                        # Bayesian fields — streamed so frontend can show belief state
                        "bayesian_entropy":        state_update.get("bayesian_entropy", 0.0),
                        "bayesian_top_cause":      state_update.get("bayesian_top_cause"),
                        "bayesian_beliefs":        state_update.get("bayesian_beliefs", {}),
                    }
                    yield _sse("step", event)

            yield _sse("complete", {"incident_id": incident_id})

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
            "X-Accel-Buffering": "no",   # Disable Nginx buffering if behind proxy
        },
    )


@app.post("/api/incident/{incident_id}/kill")
async def kill_incident(incident_id: str):
    """Kill switch — immediately stops the running investigation."""
    if incident_id not in active_runs:
        raise HTTPException(status_code=404, detail="Incident not found")
    active_runs[incident_id] = False
    logger.warning(f"[API] Kill switch activated for {incident_id}")
    return {"killed": True, "incident_id": incident_id}


@app.post("/api/incident/{incident_id}/approve")
async def approve_action(incident_id: str):
    """
    Human approval for a blocked action.

    For the hackathon: the frontend calls this after the user clicks Approve
    on the UEBA panel. In production this would resume the graph from a
    checkpoint with the approval flag set in state.
    """
    logger.info(f"[API] Human approval received for {incident_id}")
    # TODO: Implement checkpoint resume with LangGraph persistence
    # For now: return 200 so the frontend can update the UEBA panel
    return {"approved": True, "incident_id": incident_id, "note": "Checkpoint resume not yet implemented"}


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── SSE helper ────────────────────────────────────────────────────────────────

def _sse(event_type: str, data: dict) -> str:
    """Format a server-sent event."""
    payload = json.dumps({"type": event_type, **data})
    return f"data: {payload}\n\n"
