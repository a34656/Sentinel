"""
memory_agent.py — The Memory Agent.

Two operations:
  lookup → Called at the start of every incident.
           Queries Supabase for the 5 most recent resolved incidents
           so the Master can reference prior context.

  store  → Called at the end of every resolved incident.
           Persists the root cause, fix, confidence score, and scripts
           to Supabase for future lookups.

For the hackathon this uses simple recency-based lookup (not vector search).
Vector similarity search can be added post-hackathon using pgvector.
"""

import json
import uuid
from datetime import datetime

from supabase import create_client, Client
from loguru import logger

from core.state import AgentState
from core.config import config


# Lazy-initialise so startup doesn't fail if Supabase keys are missing
_client: Client | None = None

TABLE = "incident_memory"


def _get_client() -> Client | None:
    global _client
    if _client is None:
        if config.SUPABASE_URL and config.SUPABASE_KEY:
            try:
                _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
            except Exception as exc:
                logger.warning(f"[Memory] Supabase client initialization failed: {exc} — memory disabled")
                _client = None
        else:
            logger.warning("[Memory] Supabase not configured — memory disabled")
    return _client


# ── Lookup ────────────────────────────────────────────────────────────────────

def lookup(state: AgentState) -> AgentState:
    logger.info("[Memory] Looking up prior incidents...")
    client = _get_client()

    if not client:
        return {
            **state,
            "prior_incidents": [],
            "current_worker": "memory_agent",
            "step_log": ["[Memory] Supabase not configured — skipping memory lookup"],
        }

    try:
        result = (
            client.table(TABLE)
            .select("incident_prompt, root_cause, confidence_score, fix_applied, created_at")
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )
        prior = result.data or []
        log_entry = f"[Memory] Found {len(prior)} prior incident(s)"
    except Exception as exc:
        logger.error(f"[Memory] Lookup failed: {exc}")
        prior = []
        log_entry = f"[Memory] ⚠️  Lookup failed — {exc}"

    logger.info(log_entry)
    return {
        **state,
        "prior_incidents": prior,
        "current_worker": "memory_agent",
        "step_log": [log_entry],
    }


# ── Store ─────────────────────────────────────────────────────────────────────

def store(state: AgentState) -> AgentState:
    logger.info("[Memory] Storing resolved incident...")
    client = _get_client()

    if not client:
        return {
            **state,
            "step_log": ["[Memory] Supabase not configured — skipping memory store"],
        }

    try:
        record = {
            "id": str(uuid.uuid4()),
            "created_at": datetime.utcnow().isoformat(),
            "incident_id": state.get("incident_id"),
            "incident_prompt": state.get("incident_prompt"),
            "root_cause": state.get("root_cause"),
            "confidence_score": state.get("confidence_score", 0.0),
            "fix_applied": state.get("fix_applied", False),
            "fix_blocked": bool(state.get("fix_blocked_reason")),
            "notion_url": state.get("notion_page_url"),
            "scripts_count": len(state.get("scripts_executed", [])),
            "scripts_json": json.dumps(state.get("scripts_executed", []))[:5000],
        }
        client.table(TABLE).insert(record).execute()
        log_entry = "[Memory] ✅ Incident stored to long-term memory"
    except Exception as exc:
        logger.error(f"[Memory] Store failed: {exc}")
        log_entry = f"[Memory] ⚠️  Store failed — {exc}"

    logger.info(log_entry)
    return {
        **state,
        "step_log": [log_entry],
    }
