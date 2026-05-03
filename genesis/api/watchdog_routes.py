"""
api/watchdog_routes.py — Watchdog Monitoring Endpoints

Separate from server.py to keep the HTTP surface clean.
Handles: start/stop watchdog, get baseline status, manual tier-1 check,
force tier-2 classification, run consolidation manually.

Mounted in server.py:
    from api.watchdog_routes import router as watchdog_router
    app.include_router(watchdog_router)
"""

import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from loguru import logger

from core.config import config

router = APIRouter(prefix="/api/watchdog", tags=["watchdog"])

# Scheduler state
_scheduler_task: Optional[asyncio.Task] = None
_watchdog_running = False
_last_cycle_at: Optional[str] = None
_last_alerts: list = []
_total_cycles = 0
_total_investigations_triggered = 0


# ── Scheduler ────────────────────────────────────────────────────────────────

async def start_watchdog_scheduler():
    """Start the background watchdog loop. Called from server lifespan."""
    global _scheduler_task, _watchdog_running
    if _watchdog_running:
        return
    _watchdog_running = True
    _scheduler_task = asyncio.create_task(_watchdog_loop())
    logger.info(f"[Watchdog] Scheduler started (interval: {config.WATCHDOG_INTERVAL_SECONDS}s)")


async def stop_watchdog_scheduler():
    """Stop the background watchdog loop."""
    global _watchdog_running, _scheduler_task
    _watchdog_running = False
    if _scheduler_task:
        _scheduler_task.cancel()
        _scheduler_task = None
    logger.info("[Watchdog] Scheduler stopped")


async def _watchdog_loop():
    """Main watchdog loop — runs every WATCHDOG_INTERVAL_SECONDS."""
    global _last_cycle_at, _last_alerts, _total_cycles, _total_investigations_triggered

    while _watchdog_running:
        try:
            _last_cycle_at = datetime.utcnow().isoformat()
            _total_cycles += 1

            from tools.watchdog import run_watchdog_cycle
            prompt = await run_watchdog_cycle(_trigger_investigation)

            if prompt:
                _total_investigations_triggered += 1
                logger.info(f"[Watchdog] Investigation #{_total_investigations_triggered} triggered")

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error(f"[Watchdog] Loop error: {exc}")

        await asyncio.sleep(config.WATCHDOG_INTERVAL_SECONDS)


async def _trigger_investigation(prompt: str):
    """Trigger a full Genesis investigation from the watchdog."""
    import uuid
    import httpx

    incident_id = str(uuid.uuid4())
    logger.info(f"[Watchdog] Auto-triggering investigation {incident_id}: {prompt[:80]}")

    # Call our own API internally
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                "http://localhost:8000/api/incident",
                json={"prompt": prompt, "source": "watchdog"},
            )
    except Exception as exc:
        logger.warning(f"[Watchdog] Self-trigger failed: {exc} — incident may not have started")


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def watchdog_status():
    """Get current watchdog status and recent activity."""
    return {
        "enabled": config.WATCHDOG_ENABLED,
        "running": _watchdog_running,
        "interval_seconds": config.WATCHDOG_INTERVAL_SECONDS,
        "last_cycle_at": _last_cycle_at,
        "total_cycles": _total_cycles,
        "total_investigations_triggered": _total_investigations_triggered,
        "billing_threshold_pct": config.WATCHDOG_BILLING_THRESHOLD * 100,
        "error_threshold_multiplier": config.WATCHDOG_ERROR_THRESHOLD,
    }


@router.post("/start")
async def start_watchdog():
    """Manually start the watchdog if it's stopped."""
    if _watchdog_running:
        return {"already_running": True}
    await start_watchdog_scheduler()
    return {"started": True}


@router.post("/stop")
async def stop_watchdog():
    """Manually stop the watchdog."""
    await stop_watchdog_scheduler()
    return {"stopped": True}


@router.post("/check/tier1")
async def run_tier1_check():
    """
    Manually trigger a Tier 1 threshold check.
    Returns raw alerts without triggering an investigation.
    Useful for testing and verifying baselines.
    """
    try:
        from tools.watchdog import run_tier1_checks
        alerts = run_tier1_checks()
        return {
            "alerts_count": len(alerts),
            "alerts": [a.to_dict() for a in alerts],
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/check/tier2")
async def run_tier2_check(background_tasks: BackgroundTasks):
    """
    Manually trigger Tier 1 + Tier 2 classification.
    If Tier 2 decides to investigate, starts a full investigation in the background.
    """
    try:
        from tools.watchdog import run_tier1_checks, run_tier2_classification
        alerts = run_tier1_checks()

        if not alerts:
            return {"investigated": False, "reason": "No Tier 1 alerts detected"}

        prompt = run_tier2_classification(alerts)
        if not prompt:
            return {
                "investigated": False,
                "reason": "Tier 2 classified alerts as not worth investigating",
                "alerts": [a.to_dict() for a in alerts],
            }

        background_tasks.add_task(_trigger_investigation, prompt)
        return {
            "investigated": True,
            "prompt": prompt,
            "alerts": [a.to_dict() for a in alerts],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/consolidate")
async def run_consolidation(background_tasks: BackgroundTasks):
    """
    Manually trigger the nightly memory consolidation job.
    Runs in the background — returns immediately with a job ID.
    """
    background_tasks.add_task(_run_consolidation_task)
    return {
        "started": True,
        "message": "Consolidation job started in background. Check logs for results.",
        "timestamp": datetime.utcnow().isoformat(),
    }


async def _run_consolidation_task():
    try:
        from tools.consolidation import run_consolidation
        results = run_consolidation()
        logger.info(f"[Watchdog] Consolidation complete: {results}")
    except Exception as exc:
        logger.error(f"[Watchdog] Consolidation failed: {exc}")


@router.get("/baselines")
async def get_baselines():
    """Return the current learned baselines for Tier 1 checks."""
    import json, os
    from tools.watchdog import BASELINE_PATH
    if not os.path.exists(BASELINE_PATH):
        return {"baselines": {}, "note": "No baselines learned yet — run a few cycles first"}
    try:
        with open(BASELINE_PATH) as f:
            return {"baselines": json.load(f)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/baselines")
async def reset_baselines():
    """Reset all learned baselines. Use after major infrastructure changes."""
    import os
    from tools.watchdog import BASELINE_PATH
    if os.path.exists(BASELINE_PATH):
        os.remove(BASELINE_PATH)
    return {"reset": True, "message": "Baselines cleared. Will re-learn from next cycle."}


@router.get("/memory/rules")
async def get_semantic_rules():
    """Return all active Layer 3 semantic rules."""
    try:
        from core.memory_layers import _get_client
        client = _get_client()
        if not client:
            return {"rules": [], "note": "Supabase not configured"}
        result = (
            client.table("semantic_rules")
            .select("*")
            .eq("is_active", True)
            .order("confidence", desc=True)
            .execute()
        )
        return {"rules": result.data or [], "count": len(result.data or [])}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/memory/episodes")
async def get_recent_episodes(limit: int = 20):
    """Return recent Layer 2 episodic memories."""
    try:
        from core.memory_layers import _get_client
        client = _get_client()
        if not client:
            return {"episodes": [], "note": "Supabase not configured"}
        result = (
            client.table("episodic_memory")
            .select("incident_id, incident_prompt, root_cause, confidence_score, decay_score, created_at, is_archived")
            .eq("is_archived", False)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return {"episodes": result.data or [], "count": len(result.data or [])}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
