"""
scribe.py — The Scribe worker.

Two modes:
  read_runbooks  → Called at the start of every incident.
                   Pulls internal runbooks and past post-mortems from Notion
                   so the Master has context about what "normal" looks like.

  publish_report → Called at the end of a resolved incident.
                   Receives the completed investigation summary and creates
                   a structured Notion page with the post-mortem content.
"""

import os
from datetime import datetime

from notion_client import Client
from loguru import logger

from core.state import AgentState
from core.config import config


notion = Client(auth=config.NOTION_API_KEY)

# How many runbook pages to pull at the start of each investigation
MAX_RUNBOOKS = 5


# ── Read mode ─────────────────────────────────────────────────────────────────

def read_runbooks(state: AgentState) -> AgentState:
    """Pull relevant runbooks from Notion to give Master context."""
    logger.info("[Scribe] Reading runbooks from Notion...")

    if not config.NOTION_API_KEY or not config.NOTION_DATABASE_ID:
        logger.warning("[Scribe] Notion not configured — skipping runbook read")
        return {
            **state,
            "current_worker": "scribe",
            "step_log": ["[Scribe] Notion not configured — proceeding without runbooks"],
        }

    try:
        response = notion.databases.query(
            database_id=config.NOTION_DATABASE_ID,
            page_size=MAX_RUNBOOKS,
            sorts=[{"timestamp": "last_edited_time", "direction": "descending"}],
        )

        pages = response.get("results", [])
        combined = []

        for page in pages:
            title = _get_page_title(page)
            content = _get_page_content(page["id"])
            combined.append(f"### {title}\n{content[:1500]}")

        context = "\n\n".join(combined) if combined else "No runbooks found"
        log_entry = f"[Scribe] Loaded {len(pages)} runbooks from Notion"

    except Exception as exc:
        logger.error(f"[Scribe] Runbook read failed: {exc}")
        context = f"[Runbook read failed: {exc}]"
        log_entry = f"[Scribe] ⚠️  Runbook read failed — {exc}"

    logger.info(log_entry)
    return {
        **state,
        "current_worker": "scribe",
        "documentation_context": (state.get("documentation_context") or "") + "\n\n" + context,
        "step_log": [log_entry],
    }


# ── Write mode ────────────────────────────────────────────────────────────────

def publish_report(state: AgentState) -> AgentState:
    """Create a structured post-mortem page in Notion."""
    logger.info("[Scribe] Publishing post-mortem to Notion...")

    if not config.NOTION_API_KEY or not config.NOTION_DATABASE_ID:
        logger.warning("[Scribe] Notion not configured — skipping publish")
        return {
            **state,
            "current_worker": "scribe",
            "step_log": ["[Scribe] Notion not configured — skipping publish"],
        }

    try:
        page = notion.pages.create(
            parent={"database_id": config.NOTION_DATABASE_ID},
            properties={
                "Name": {
                    "title": [{"text": {"content": f"Incident Post-Mortem — {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"}}]
                },
                "Status": {"select": {"name": "Resolved" if state.get("fix_applied") else "Blocked"}},
            },
            children=_build_page_blocks(state),
        )

        page_url = page.get("url", "")
        log_entry = f"[Scribe] ✅ Post-mortem published: {page_url}"
        logger.info(log_entry)

        return {
            **state,
            "current_worker": "scribe",
            "notion_page_url": page_url,
            "step_log": [log_entry],
        }

    except Exception as exc:
        logger.error(f"[Scribe] Publish failed: {exc}")
        return {
            **state,
            "current_worker": "scribe",
            "step_log": [f"[Scribe] ⚠️  Notion publish failed — {exc}"],
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_page_title(page: dict) -> str:
    try:
        props = page.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                parts = prop["title"]
                return "".join(p["plain_text"] for p in parts)
    except Exception:
        pass
    return "Untitled"


def _get_page_content(page_id: str) -> str:
    try:
        blocks = notion.blocks.children.list(block_id=page_id)
        texts = []
        for block in blocks.get("results", []):
            btype = block.get("type")
            if btype in ("paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item"):
                rich = block.get(btype, {}).get("rich_text", [])
                texts.append("".join(r["plain_text"] for r in rich))
        return "\n".join(texts)
    except Exception:
        return ""


def _build_page_blocks(state: AgentState) -> list[dict]:
    """Build Notion block content for the post-mortem page."""
    def heading(text: str, level: int = 2) -> dict:
        return {
            "object": "block",
            "type": f"heading_{level}",
            f"heading_{level}": {"rich_text": [{"type": "text", "text": {"content": text}}]},
        }

    def paragraph(text: str) -> dict:
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]},
        }

    blocks = [
        heading("Incident Summary", 1),
        paragraph(state.get("incident_prompt", "No prompt recorded")),
        heading("Root Cause"),
        paragraph(state.get("root_cause") or "Could not be determined"),
        heading("Confidence Score"),
        paragraph(f"{state.get('confidence_score', 0.0) * 100:.0f}%"),
        heading("Corroborating Signals"),
        paragraph("\n".join(f"• {s}" for s in state.get("corroborating_signals", []))),
        heading("Fix Applied"),
        paragraph(state.get("proposed_fix") or "No fix applied"),
        heading("Fix Status"),
        paragraph(
            "✅ Applied automatically" if state.get("fix_applied")
            else f"⛔ Blocked — {state.get('fix_blocked_reason', 'unknown reason')}"
        ),
        heading("Scripts Executed"),
    ]

    for i, script in enumerate(state.get("scripts_executed", []), 1):
        blocks.append(paragraph(
            f"Script {i} — {'✅ success' if script.get('success') else '❌ failed'}\n"
            f"Output: {script.get('output', '')[:400]}"
        ))

    if state.get("final_report_path"):
        blocks.append(heading("PDF Report"))
        blocks.append(paragraph(f"Saved to: {state['final_report_path']}"))

    return blocks
