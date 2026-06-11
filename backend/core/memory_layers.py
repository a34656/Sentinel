"""
core/memory_layers.py — Three-Tier Memory Architecture

Layer 1 — Working memory:  lives in AgentState (context window only, free)
Layer 2 — Episodic memory: Supabase episodic_memory table, with decay + vector search
Layer 3 — Semantic memory: Supabase semantic_rules table, human+AI editable rules

Usage pattern in every investigation:
    1. inject_memory_context(state, prompt) → returns ~1300 tokens of context
    2. After resolution: save_episode(state) → persists to Layer 2
    3. Nightly: tools/consolidation.py promotes Layer 2 → Layer 3 rules

The three-layer separation solves the continuous monitoring memory problem:
- Layer 3 is flat and small (10 rules ≈ 500 tokens) regardless of uptime
- Layer 2 is bounded by decay (max 300 active episodes at any time)
- Layer 1 is ephemeral — zero storage cost
"""

import json
import uuid
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger

from core.config import config


# ── Lazy Supabase client ──────────────────────────────────────────────────────

_client = None

def _get_client():
    global _client
    if _client is None and config.SUPABASE_URL and config.SUPABASE_KEY:
        try:
            from supabase import create_client
            _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
        except Exception as exc:
            logger.warning(f"[MemoryLayers] Supabase unavailable: {exc}")
    return _client


# ── Lightweight embedding ─────────────────────────────────────────────────────
# 8-dimensional concept vector — avoids a separate embedding API call.
# Maps text to relevance scores across 8 infrastructure concepts.
# In production: swap for text-embedding-3-small (1536-dim) for better recall.

_CONCEPTS = [
    "billing cost spend aws gcp cloud",
    "cpu memory performance latency timeout",
    "security iam permission denied access",
    "database connection pool query slow",
    "network dns routing firewall ingress",
    "deployment config environment variable release",
    "storage disk s3 bucket filesystem",
    "authentication oauth token expired session",
]

def _embed(text: str) -> list[float]:
    """
    Produce an 8-dim embedding by scoring text against 8 concept clusters.
    Each dimension = fraction of concept keywords present in text.
    Fast, free, no API call. Sufficient for prototype-level similarity search.
    """
    text_lower = str(text).lower()
    scores = []
    for concept in _CONCEPTS:
        keywords = concept.split()
        hits = sum(1 for kw in keywords if kw in text_lower)
        scores.append(round(hits / len(keywords), 4))
    return scores


# ── Layer 3: Semantic rules ───────────────────────────────────────────────────

def get_layer3_rules(tags: Optional[list[str]] = None, limit: int = 10) -> str:
    """
    Fetch active semantic rules from Layer 3.
    Returns a formatted string ready to inject into the Master's context.
    ~500 tokens regardless of how long Genesis has been running.
    """
    client = _get_client()
    if not client:
        return ""

    try:
        query = (
            client.table("semantic_rules")
            .select("rule_text, applies_to, confidence, times_confirmed, times_wrong")
            .eq("is_active", True)
            .order("confidence", desc=True)
            .limit(limit)
        )

        if tags:
            # Filter rules that overlap with provided tags
            query = query.overlaps("applies_to", tags)

        result = query.execute()
        rules = result.data or []

        if not rules:
            return ""

        lines = ["SYSTEM KNOWLEDGE (learned from past incidents — treat as strong prior):"]
        for r in rules:
            reliability = ""
            if r["times_confirmed"] + r["times_wrong"] > 0:
                rate = r["times_confirmed"] / (r["times_confirmed"] + r["times_wrong"])
                reliability = f" [confirmed {rate*100:.0f}% of {r['times_confirmed']+r['times_wrong']} uses]"
            lines.append(f"• {r['rule_text']}{reliability}")

        return "\n".join(lines)

    except Exception as exc:
        logger.warning(f"[MemoryLayers] Layer3 fetch failed: {exc}")
        return ""


def record_rule_outcome(rule_text: str, was_correct: bool) -> None:
    """After an investigation, record whether each applied rule was correct."""
    client = _get_client()
    if not client:
        return
    try:
        result = client.table("semantic_rules").select("id, times_confirmed, times_wrong").eq("rule_text", rule_text).execute()
        if not result.data:
            return
        row = result.data[0]
        update = (
            {"times_confirmed": row["times_confirmed"] + 1}
            if was_correct
            else {"times_wrong": row["times_wrong"] + 1}
        )
        # Deactivate rules with more than 30% failure rate after 10+ uses
        total = row["times_confirmed"] + row["times_wrong"] + 1
        if total >= 10:
            wrong = row["times_wrong"] + (0 if was_correct else 1)
            if wrong / total > 0.3:
                update["is_active"] = False
                logger.warning(f"[MemoryLayers] Rule deactivated (>30% failure rate): {rule_text[:80]}")

        client.table("semantic_rules").update(update).eq("id", row["id"]).execute()
    except Exception as exc:
        logger.warning(f"[MemoryLayers] Rule outcome record failed: {exc}")


# ── Layer 2: Episodic memory ──────────────────────────────────────────────────

def query_layer2(prompt: str, top_k: int = 3) -> list[dict]:
    """
    Vector similarity search over active episodic memories.
    Returns top-K similar past incidents, blended with decay score.
    """
    client = _get_client()
    if not client:
        return []

    try:
        embedding = _embed(prompt)
        result = client.rpc("match_episodic_memories", {
            "query_embedding": embedding,
            "match_threshold": 0.5,
            "match_count": top_k,
        }).execute()

        return [
            {
                "incident_id":      row.get("incident_id"),
                "incident_prompt":  row.get("incident_prompt"),
                "root_cause":       row.get("root_cause"),
                "resolution":       row.get("resolution"),
                "confidence_score": float(row.get("confidence_score") or 0),
                "similarity":       float(row.get("similarity") or 0),
                "decay_score":      float(row.get("decay_score") or 1.0),
            }
            for row in (result.data or [])
        ]

    except Exception as exc:
        logger.warning(f"[MemoryLayers] Layer2 query failed: {exc}")
        return []


def save_episode(
    incident_id: str,
    incident_prompt: str,
    root_cause: Optional[str],
    resolution: Optional[str],
    confidence_score: float,
    fix_applied: bool,
    tags: Optional[list[str]] = None,
) -> None:
    """Persist a resolved incident to Layer 2 episodic memory."""
    client = _get_client()
    if not client:
        return

    try:
        embedding = _embed(f"{incident_prompt} {root_cause or ''} {resolution or ''}")
        client.table("episodic_memory").insert({
            "id": str(uuid.uuid4()),
            "incident_id": incident_id,
            "incident_prompt": incident_prompt,
            "root_cause": root_cause,
            "resolution": resolution,
            "confidence_score": confidence_score,
            "fix_applied": fix_applied,
            "tags": tags or _auto_tag(incident_prompt),
            "embedding": embedding,
            "decay_score": 1.0,
            "reinforcement_count": 0,
            "is_archived": False,
        }).execute()
        logger.info(f"[MemoryLayers] Episode saved for incident {incident_id}")

    except Exception as exc:
        logger.warning(f"[MemoryLayers] Episode save failed: {exc}")


def reinforce_episode(incident_id: str) -> None:
    """
    Call when a past memory was retrieved and proved correct.
    Resets decay_score to 1.0 and increments reinforcement_count.
    """
    client = _get_client()
    if not client:
        return
    try:
        result = client.table("episodic_memory").select("id, reinforcement_count").eq("incident_id", incident_id).execute()
        if result.data:
            row = result.data[0]
            client.table("episodic_memory").update({
                "decay_score": 1.0,
                "reinforcement_count": row["reinforcement_count"] + 1,
                "last_reinforced_at": datetime.utcnow().isoformat(),
            }).eq("id", row["id"]).execute()
    except Exception as exc:
        logger.warning(f"[MemoryLayers] Reinforce failed: {exc}")


def decay_old_episodes(decay_factor: float = 0.05, archive_threshold: float = 0.2) -> int:
    """
    Nightly decay pass — called by consolidation.py.
    Reduces decay_score of all active episodes by decay_factor.
    Archives episodes below archive_threshold.
    Returns count of archived episodes.
    """
    client = _get_client()
    if not client:
        return 0
    try:
        # Fetch all active episodes
        result = client.table("episodic_memory").select("id, decay_score").eq("is_archived", False).execute()
        rows = result.data or []
        archived = 0

        for row in rows:
            new_score = round(row["decay_score"] - decay_factor, 4)
            if new_score <= archive_threshold:
                client.table("episodic_memory").update({"is_archived": True, "decay_score": 0.0}).eq("id", row["id"]).execute()
                archived += 1
            else:
                client.table("episodic_memory").update({"decay_score": new_score}).eq("id", row["id"]).execute()

        logger.info(f"[MemoryLayers] Decay pass: {len(rows)} episodes processed, {archived} archived")
        return archived

    except Exception as exc:
        logger.warning(f"[MemoryLayers] Decay pass failed: {exc}")
        return 0


# ── Combined context injection ────────────────────────────────────────────────

def inject_memory_context(incident_prompt: str) -> str:
    """
    Assemble the full memory context to inject at the start of an investigation.
    Combines Layer 3 rules + Layer 2 similar episodes.
    Target: ~1300 tokens regardless of how long the system has been running.
    """
    tags = _auto_tag(incident_prompt)

    layer3 = get_layer3_rules(tags=tags, limit=8)
    layer2_matches = query_layer2(incident_prompt, top_k=3)

    parts = []

    if layer3:
        parts.append(layer3)

    if layer2_matches:
        parts.append("\nSIMILAR PAST INCIDENTS (ranked by relevance × recency):")
        for m in layer2_matches:
            similarity_pct = round(float(m.get("similarity" or 0)) * 100)
            decay_pct = round(float(m.get("decay_score" or 1.0)) * 100)
            parts.append(
                f"• [{similarity_pct}% similar, {decay_pct}% fresh] "
                f"{m.get('incident_prompt', '')[:100]}\n"
                f"  Root cause: {m.get('root_cause', 'unknown')}\n"
                f"  Resolution: {m.get('resolution', 'unknown')}"
            )

    if not parts:
        return "No prior memory context available."

    return "\n\n".join(parts)


# ── Auto-tagger ───────────────────────────────────────────────────────────────

def _auto_tag(text: str) -> list[str]:
    """Assign tags from a fixed taxonomy based on keywords in the text."""
    text_lower = text.lower()
    tag_map = {
        "billing":    ["cost", "bill", "spend", "price", "charge", "invoice"],
        "aws":        ["aws", "amazon", "ec2", "s3", "rds", "lambda", "cloudwatch", "iam"],
        "gcp":        ["gcp", "google cloud", "cloud run", "bigquery", "gke"],
        "database":   ["database", "db", "postgres", "mysql", "rds", "mongo", "connection"],
        "network":    ["network", "dns", "latency", "timeout", "ingress", "routing"],
        "security":   ["security", "iam", "permission", "access denied", "unauthorized"],
        "performance":["cpu", "memory", "performance", "slow", "latency", "spike"],
        "deployment": ["deploy", "release", "rollout", "config", "env", "variable"],
        "storage":    ["storage", "disk", "s3", "bucket", "filesystem", "volume"],
    }
    return [tag for tag, keywords in tag_map.items() if any(kw in text_lower for kw in keywords)]
