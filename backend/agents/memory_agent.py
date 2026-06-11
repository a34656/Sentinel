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
    """
    Layer 1 (legacy flat lookup) + Layer 2 (episodic) + Layer 3 (semantic rules)
    + Obsidian vault context + human corrections.
    All assembled into a single memory_context string (~1300 tokens flat).
    """
    logger.info("[Memory] Looking up prior incidents (three-tier)...")

    # ── Three-tier memory context ─────────────────────────────────────────
    try:
        from core.memory_layers import inject_memory_context
        memory_context = inject_memory_context(state["incident_prompt"])
    except Exception as exc:
        logger.warning(f"[Memory] Memory layers unavailable: {exc}")
        memory_context = ""

    # ── Obsidian vault context ────────────────────────────────────────────
    obsidian_context = ""
    try:
        from tools.obsidian_sync import search_vault, read_human_corrections
        vault_notes = search_vault(state["incident_prompt"], max_results=3)
        corrections = read_human_corrections()
        parts = []
        if vault_notes:
            parts.append(vault_notes)
        if corrections:
            parts.append("HUMAN CORRECTIONS TO PAST GENESIS ANALYSES:\n" + "\n".join(corrections))
        obsidian_context = "\n\n".join(parts)
    except Exception as exc:
        logger.debug(f"[Memory] Obsidian unavailable: {exc}")

    # ── Phoenix trace context ─────────────────────────────────────────────
    phoenix_context = ""
    try:
        phoenix_context = _query_phoenix_traces(state["incident_prompt"])
    except Exception as exc:
        logger.debug(f"[Memory] Phoenix unavailable: {exc}")

    # ── Legacy flat lookup (keep for backwards compatibility) ────────────
    client = _get_client()
    prior = []
    if client:
        try:
            result = (
                client.table(TABLE)
                .select("incident_prompt, root_cause, confidence_score, fix_applied, created_at")
                .order("created_at", desc=True)
                .limit(5)
                .execute()
            )
            prior = result.data or []
        except Exception as exc:
            logger.warning(f"[Memory] Flat lookup failed: {exc}")

    parts = []
    if memory_context:
        parts.append(f"Three-tier memory: {memory_context[:200]}...")
    if obsidian_context:
        parts.append(f"Obsidian: {len(obsidian_context)} chars loaded")
    if phoenix_context:
        parts.append(f"Phoenix traces: {len(phoenix_context)} chars loaded")
    if prior:
        parts.append(f"Legacy episodes: {len(prior)}")
    log_entry = f"[Memory] Context loaded — {' | '.join(parts) or 'nothing found'}"
    logger.info(log_entry)

    return {
        **state,
        "prior_incidents": prior,
        "memory_context": memory_context,
        "obsidian_context": obsidian_context,
        "phoenix_context": phoenix_context,
        "current_worker": "memory_agent",
        "step_log": [log_entry],
        "bayesian_beliefs": {},
        "bayesian_entropy": 0.0,
        "bayesian_top_cause": None,
        "bayesian_suggestion": None,
    }


# ── Store ─────────────────────────────────────────────────────────────────────

def store(state: AgentState) -> AgentState:
    logger.info("[Memory] Storing resolved incident (flat + episodic + Obsidian)...")
    client = _get_client()
    log_parts = []

    # ── Legacy flat store (Table: incident_memory) ────────────────────────
    if client:
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
            log_parts.append("flat store ✅")
        except Exception as exc:
            logger.error(f"[Memory] Flat store failed: {exc}")
            log_parts.append(f"flat store ⚠️ {exc}")

    # ── Layer 2 episodic store ────────────────────────────────────────────
    try:
        from core.memory_layers import save_episode
        save_episode(
            incident_id=state.get("incident_id", ""),
            incident_prompt=state.get("incident_prompt", ""),
            root_cause=state.get("root_cause"),
            resolution=state.get("proposed_fix"),
            confidence_score=state.get("confidence_score", 0.0),
            fix_applied=state.get("fix_applied", False),
        )
        log_parts.append("episodic Layer2 ✅")
    except Exception as exc:
        logger.warning(f"[Memory] Layer2 store failed: {exc}")
        log_parts.append(f"episodic ⚠️")

    # ── Obsidian post-mortem ──────────────────────────────────────────────
    try:
        from tools.obsidian_sync import write_postmortem_to_vault
        obsidian_path = write_postmortem_to_vault(
            incident_id=state.get("incident_id", ""),
            prompt=state.get("incident_prompt", ""),
            root_cause=state.get("root_cause"),
            resolution=state.get("proposed_fix"),
            confidence_score=state.get("confidence_score", 0.0),
            step_log=state.get("step_log", []),
            notion_url=state.get("notion_page_url"),
        )
        if obsidian_path:
            log_parts.append(f"Obsidian ✅ {obsidian_path.name}")
    except Exception as exc:
        logger.debug(f"[Memory] Obsidian write skipped: {exc}")

    log_entry = f"[Memory] Store complete — {' | '.join(log_parts)}"
    logger.info(log_entry)
    return {
        **state,
        "step_log": [log_entry],
    }


# ── Phoenix trace query ───────────────────────────────────────────────────────

def _query_phoenix_traces(incident_prompt: str) -> str:
    """
    Query Phoenix for recent failed investigation spans similar to this prompt.
    Uses the Phoenix HTTP API directly — no MCP client needed.
    Phoenix must be running locally: phoenix serve (default port 6006)
    """
    import httpx

    PHOENIX_URL = os.getenv("PHOENIX_URL", "http://localhost:6006")
    project = os.getenv("ARIZE_PROJECT_NAME", "genesis-compliance")

    try:
        # Query spans from the last 24 hours that had errors or low confidence
        response = httpx.post(
            f"{PHOENIX_URL}/v1/spans",
            json={
                "project_name": project,
                "filter_condition": "span_kind == 'CHAIN'",
                "limit": 10,
                "sort": {"col": {"name": "startTime"}, "dir": "desc"},
            },
            timeout=5.0,
        )

        if response.status_code != 200:
            logger.debug(f"[Memory] Phoenix returned {response.status_code}")
            return ""

        data = response.json()
        spans = data.get("data", [])

        if not spans:
            return ""

        # Extract what's useful for the Master: worker steps that failed,
        # and what the Master reasoned about similar incidents
        useful = []
        for span in spans[:5]:
            attrs = span.get("attributes", {})
            status = span.get("status", {})
            name = span.get("name", "")

            # Only care about failed or low-confidence spans
            if status.get("statusCode") == "ERROR":
                useful.append(
                    f"PAST FAILURE — {name}: {status.get('message', 'unknown error')[:200]}"
                )

            # Extract LLM input/output for master reasoning spans
            input_val = attrs.get("input.value", "")
            output_val = attrs.get("output.value", "")
            if "master" in name.lower() and output_val:
                try:
                    out = json.loads(output_val) if isinstance(output_val, str) else output_val
                    reasoning = out.get("reasoning", "")
                    root_cause = out.get("root_cause", "")
                    confidence = out.get("confidence_score", 0)
                    if reasoning:
                        useful.append(
                            f"PAST REASONING (confidence {confidence:.2f}): "
                            f"Root cause: {root_cause} | Reasoning: {reasoning[:300]}"
                        )
                except Exception:
                    pass

        if not useful:
            return ""

        return (
            "PHOENIX TRACE CONTEXT — What Genesis did in recent similar investigations:\n"
            + "\n".join(useful)
        )

    except Exception as exc:
        logger.debug(f"[Memory] Phoenix query failed: {exc}")
        return ""