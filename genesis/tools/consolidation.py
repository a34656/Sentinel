"""
tools/consolidation.py — Nightly Memory Consolidation Job

Runs once per day (via cron or APScheduler).
Reads the last 7 days of Layer 2 episodic memories and extracts
generalised rules into Layer 3 semantic memory.

This is the "sleep and dream" process — the agent consolidates experience
into reusable knowledge, mirroring how human experts develop intuition.

After 30 incidents, the agent stops re-deriving the same patterns from scratch.
It reads 10 compressed rules (~500 tokens) instead of 30 raw incidents (~15,000 tokens).

Run manually:
    python -m tools.consolidation

Run via cron (add to crontab):
    0 3 * * * cd /app && python -m tools.consolidation >> /var/log/genesis/consolidation.log 2>&1
"""

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

# Allow running as a script from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import config
from core.memory_layers import decay_old_episodes, get_layer3_rules, _get_client


CONSOLIDATION_PROMPT = Path(__file__).parent.parent / "prompts" / "consolidation.md"


def _load_prompt() -> str:
    if CONSOLIDATION_PROMPT.exists():
        return CONSOLIDATION_PROMPT.read_text(encoding="utf-8")
    return _DEFAULT_CONSOLIDATION_PROMPT


def run_consolidation() -> dict:
    """
    Main entry point. Returns a summary dict with counts.
    """
    logger.info("[Consolidation] Starting nightly consolidation job...")
    results = {
        "episodes_read": 0,
        "rules_created": 0,
        "rules_updated": 0,
        "episodes_archived": 0,
        "started_at": datetime.utcnow().isoformat(),
    }

    client = _get_client()
    if not client:
        logger.warning("[Consolidation] Supabase not available — skipping")
        return results

    # Step 1: Decay old episodes
    archived = decay_old_episodes(decay_factor=0.05, archive_threshold=0.2)
    results["episodes_archived"] = archived

    # Step 2: Fetch recent episodes (last 7 days)
    cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
    try:
        response = (
            client.table("episodic_memory")
            .select("incident_prompt, root_cause, resolution, confidence_score, fix_applied, tags, created_at")
            .eq("is_archived", False)
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        episodes = response.data or []
        results["episodes_read"] = len(episodes)
    except Exception as exc:
        logger.error(f"[Consolidation] Episode fetch failed: {exc}")
        return results

    if len(episodes) < 3:
        logger.info(f"[Consolidation] Only {len(episodes)} episodes — skipping rule extraction (need ≥3)")
        return results

    # Step 3: Extract rules via LLM
    new_rules = _extract_rules_from_episodes(episodes)

    # Step 4: Upsert rules into Layer 3
    for rule in new_rules:
        created = _upsert_rule(client, rule)
        if created:
            results["rules_created"] += 1
        else:
            results["rules_updated"] += 1

    logger.info(
        f"[Consolidation] Complete. "
        f"Episodes: {results['episodes_read']} | "
        f"Rules created: {results['rules_created']} | "
        f"Rules updated: {results['rules_updated']} | "
        f"Archived: {results['episodes_archived']}"
    )
    return results


def _extract_rules_from_episodes(episodes: list[dict]) -> list[dict]:
    """
    Use a cheap LLM to extract generalised rules from a batch of episodes.
    Returns list of rule dicts ready to insert into semantic_rules table.
    """
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash-lite",    # cheap model — this is a background job
            google_api_key=config.GEMINI_API_KEY,
            temperature=0.2,
        )

        episodes_text = json.dumps([
            {
                "prompt": e.get("incident_prompt", "")[:200],
                "root_cause": e.get("root_cause", ""),
                "resolution": e.get("resolution", ""),
                "confidence": e.get("confidence_score", 0),
                "tags": e.get("tags", []),
            }
            for e in episodes
        ], indent=2)

        prompt = _load_prompt()

        response = llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content=f"Here are the recent incidents:\n\n{episodes_text}"),
        ])

        text = response.content
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if not match:
            logger.warning("[Consolidation] LLM did not return a JSON array")
            return []

        rules = json.loads(match.group())
        logger.info(f"[Consolidation] Extracted {len(rules)} rules from LLM")
        return rules

    except Exception as exc:
        logger.error(f"[Consolidation] Rule extraction failed: {exc}")
        return []


def _upsert_rule(client, rule: dict) -> bool:
    """
    Insert rule if it doesn't exist; update confidence if it does.
    Returns True if created, False if updated.
    """
    rule_text = rule.get("rule_text", "").strip()
    if not rule_text or len(rule_text) < 20:
        return False

    try:
        existing = (
            client.table("semantic_rules")
            .select("id, confidence, times_confirmed")
            .eq("rule_text", rule_text)
            .execute()
        )

        if existing.data:
            row = existing.data[0]
            new_confidence = min(0.95, (row["confidence"] + rule.get("confidence", 0.7)) / 2)
            client.table("semantic_rules").update({
                "confidence": new_confidence,
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("id", row["id"]).execute()
            return False
        else:
            client.table("semantic_rules").insert({
                "rule_text": rule_text,
                "applies_to": rule.get("tags", []),
                "confidence": rule.get("confidence", 0.7),
                "source": "consolidation",
                "is_active": True,
            }).execute()
            return True

    except Exception as exc:
        logger.warning(f"[Consolidation] Rule upsert failed: {exc}")
        return False


# ── Default consolidation prompt (used if prompts/consolidation.md not found) ─

_DEFAULT_CONSOLIDATION_PROMPT = """
You are analysing a batch of resolved infrastructure incidents to extract generalised knowledge.

Your job: identify patterns that appear across multiple incidents and express them as
concise, actionable rules that can help an agent investigate future incidents faster.

Good rules are:
- Specific to observable patterns, not general advice
- Expressed as "In this system, [condition] usually means [cause]"
- Falsifiable — they can be proven wrong by a future incident

Bad rules:
- "Monitor your infrastructure" (too vague)
- "AWS costs can increase" (not a pattern)
- Single-incident observations (may not generalise)

Return ONLY a JSON array of rule objects, no prose:
[
  {
    "rule_text": "Daily billing spikes on weekends are usually the analytics batch job running longer than scheduled",
    "tags": ["billing", "aws", "batch"],
    "confidence": 0.75
  },
  ...
]

Extract between 3 and 8 rules. Only include rules supported by at least 2 incidents.
If no strong patterns exist, return an empty array: []
"""


if __name__ == "__main__":
    results = run_consolidation()
    print(json.dumps(results, indent=2))
