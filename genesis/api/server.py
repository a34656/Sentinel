"""
server.py — FastAPI backend for Genesis SRE Agent
Enhanced: Real-time backend log streaming to frontend
"""

import asyncio
import json
import uuid
from asyncio import Queue
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel

from core.config import config
from core.graph import genesis_graph
from core.state import AgentState

# ─────────────────────────────────────────────────────────────
# GLOBAL LOG EVENT QUEUE
# ─────────────────────────────────────────────────────────────

EVENT_QUEUE: Queue = Queue()

def frontend_log_sink(message):
    """
    Intercepts ALL Loguru logs and forwards them to frontend.
    """
    try:
        record = message.record

        payload = {
            "type": "log",
            "level": record["level"].name,
            "message": record["message"],
            "module": record["module"],
            "time": str(record["time"]),
        }

        EVENT_QUEUE.put_nowait(payload)

    except Exception as exc:
        print(f"Frontend log sink failed: {exc}")

# Add sink globally
logger.add(frontend_log_sink)

# ─────────────────────────────────────────────────────────────
# LIFESPAN
# ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Genesis API starting up")

    try:
        from tools.obsidian_sync import sync_vault_to_db

        synced = sync_vault_to_db()

        if synced:
            logger.info(f"[Startup] Obsidian synced {synced} vault notes")

    except Exception as exc:
        logger.warning(f"[Startup] Obsidian sync skipped: {exc}")

    if config.WATCHDOG_ENABLED:
        from api.watchdog_routes import start_watchdog_scheduler

        await start_watchdog_scheduler()
        logger.info("[Startup] Watchdog scheduler started")

    yield

    logger.info("Genesis API shutting down")

# ─────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="Genesis SRE Agent API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
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

active_runs: dict[str, bool] = {}

# ─────────────────────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────────────────────

class IncidentRequest(BaseModel):
    prompt: str

# ─────────────────────────────────────────────────────────────
# INCIDENT ROUTE
# ─────────────────────────────────────────────────────────────

@app.post("/api/incident")
async def start_incident(req: IncidentRequest):

    incident_id = str(uuid.uuid4())
    active_runs[incident_id] = True

    logger.info(f"[API] Starting incident {incident_id}")

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

    final = {
        "root_cause": None,
        "notion_page_url": None,
    }

    async def stream():

        try:
            yield _sse("init", {
                "incident_id": incident_id
            })

            async def log_stream():
                while active_runs.get(incident_id, False):
                    try:
                        event = await asyncio.wait_for(
                            EVENT_QUEUE.get(),
                            timeout=0.25
                        )

                        yield _sse("log", event)

                    except asyncio.TimeoutError:
                        continue

            log_task = log_stream()

            async for step in genesis_graph.astream(
                initial_state,
                config={"recursion_limit": 100},
                stream_mode="updates",
            ):

                if not active_runs.get(incident_id, False):
                    yield _sse("killed", {
                        "incident_id": incident_id
                    })
                    return

                # STREAM LOG EVENTS
                try:
                    while True:
                        event = EVENT_QUEUE.get_nowait()
                        yield _sse("log", event)

                except asyncio.QueueEmpty:
                    pass

                for node_name, state_update in step.items():

                    if state_update.get("root_cause"):
                        final["root_cause"] = state_update["root_cause"]

                    if state_update.get("notion_page_url"):
                        final["notion_page_url"] = state_update["notion_page_url"]

                    event = {
                        "node": node_name,
                        "step_log": state_update.get("step_log", []),
                        "confidence_score": state_update.get("confidence_score", 0.0),
                        "current_worker": state_update.get("current_worker", ""),
                        "root_cause": state_update.get("root_cause"),
                        "awaiting_human_approval": state_update.get("awaiting_human_approval", False),
                        "fix_blocked_reason": state_update.get("fix_blocked_reason"),
                        "notion_page_url": state_update.get("notion_page_url"),
                        "final_report_path": state_update.get("final_report_path"),
                        "bayesian_entropy": state_update.get("bayesian_entropy", 0.0),
                        "bayesian_top_cause": state_update.get("bayesian_top_cause"),
                        "bayesian_beliefs": state_update.get("bayesian_beliefs", {}),
                    }

                    yield _sse("step", event)

            yield _sse("complete", {
                "incident_id": incident_id,
                "root_cause": final["root_cause"],
                "notion_page_url": final["notion_page_url"],
            })

        except Exception as exc:

            logger.exception(f"[API] Stream failure: {exc}")

            yield _sse("error", {
                "message": str(exc)
            })

        finally:
            active_runs.pop(incident_id, None)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

# ─────────────────────────────────────────────────────────────
# KILL
# ─────────────────────────────────────────────────────────────

@app.post("/api/incident/{incident_id}/kill")
async def kill_incident(incident_id: str):

    if incident_id not in active_runs:
        raise HTTPException(
            status_code=404,
            detail="Incident not found"
        )

    active_runs[incident_id] = False

    logger.warning(f"[API] Kill switch activated for {incident_id}")

    return {
        "killed": True
    }

# ─────────────────────────────────────────────────────────────
# APPROVE
# ─────────────────────────────────────────────────────────────

@app.post("/api/incident/{incident_id}/approve")
async def approve_action(incident_id: str):

    logger.info(f"[API] Human approval received for {incident_id}")

    return {
        "approved": True
    }

# ─────────────────────────────────────────────────────────────
# INCIDENT HISTORY
# ─────────────────────────────────────────────────────────────

@app.get("/api/incidents")
async def list_incidents(limit: int = 20):

    try:
        from supabase import create_client

        client = create_client(
            config.SUPABASE_URL,
            config.SUPABASE_KEY,
        )

        result = (
            client.table("incident_memory")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

        return {
            "incidents": result.data or [],
            "count": len(result.data or []),
        }

    except Exception as exc:

        logger.error(f"[API] list_incidents failed: {exc}")

        return {
            "incidents": [],
            "count": 0,
            "error": str(exc),
        }

# ─────────────────────────────────────────────────────────────
# HEALTH
# ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():

    return {
        "status": "ok",
        "version": "2.0.0",
        "active_runs": len(active_runs),
    }

# ─────────────────────────────────────────────────────────────
# SSE HELPER
# ─────────────────────────────────────────────────────────────

def _sse(event_type: str, data: dict) -> str:

    payload = json.dumps({
        "type": event_type,
        **data
    })

    return f"data: {payload}\n\n"