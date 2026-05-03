"""
tools/obsidian_sync.py — Obsidian Vault ↔ Genesis Shared Epistemic Substrate

Implements the "shared epistemic substrate" concept from Karpathy's blog:
a single knowledge base that both humans and the AI agent read and write,
with neither having privileged access.

Your Obsidian vault is Layer 3 memory made human-editable.
Engineers write runbooks. Genesis writes post-mortems.
Both are read at the start of every investigation.

The novel contribution:
    Human engineers can CORRECT Genesis's past reasoning by editing notes.
    On the next investigation, Genesis reads the corrected note and doesn't
    repeat the mistake. This is a human-in-the-loop memory refinement cycle.

Setup:
    1. Set OBSIDIAN_VAULT_PATH in .env.local (absolute path to your vault)
    2. Optionally set OBSIDIAN_GENESIS_FOLDER (subfolder for Genesis to write to)
    3. Call sync_vault_to_db() on startup to index all vault notes
    4. Call write_postmortem_to_vault() after each investigation

Obsidian plugin requirement:
    None required — this operates directly on the vault's markdown files.
    If you use Obsidian Sync, files are plain .md on disk.
"""

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from core.config import config


# ── Config ────────────────────────────────────────────────────────────────────

VAULT_PATH = Path(os.getenv("OBSIDIAN_VAULT_PATH", ""))
GENESIS_FOLDER = os.getenv("OBSIDIAN_GENESIS_FOLDER", "Genesis/PostMortems")
RUNBOOK_FOLDER = os.getenv("OBSIDIAN_RUNBOOK_FOLDER", "Runbooks")

# Note types by folder pattern
NOTE_TYPE_MAP = {
    "runbook": ["runbook", "runbooks", "playbook", "playbooks", "sop"],
    "architecture": ["architecture", "arch", "design", "adr", "decisions"],
    "postmortem": ["postmortem", "post-mortem", "incident", "outage", "genesis"],
}


# ── Read: vault → Genesis ─────────────────────────────────────────────────────

def search_vault(query: str, max_results: int = 5) -> str:
    """
    Search the Obsidian vault for notes relevant to a query.
    Returns formatted markdown context ready to inject into investigation.
    Called at the start of each investigation alongside Notion runbooks.
    """
    if not VAULT_PATH or not VAULT_PATH.exists():
        return ""

    results = _search_notes(query, max_results)
    if not results:
        return ""

    parts = [f"OBSIDIAN VAULT CONTEXT (from {len(results)} relevant notes):"]
    for note in results:
        parts.append(f"\n### {note['title']} ({note['type']})")
        parts.append(note['excerpt'])

    return "\n".join(parts)


def _search_notes(query: str, max_results: int) -> list[dict]:
    """Simple keyword search across all vault .md files."""
    if not VAULT_PATH.exists():
        return []

    query_words = set(query.lower().split())
    scored = []

    for md_file in VAULT_PATH.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
            content_lower = content.lower()

            # Score by query word overlap
            hits = sum(1 for word in query_words if len(word) > 3 and word in content_lower)
            if hits == 0:
                continue

            note_type = _classify_note_type(md_file)
            # Boost runbooks and recent post-mortems
            if note_type == "runbook":
                hits *= 2
            if note_type == "postmortem":
                hits *= 1.5

            scored.append({
                "path": md_file,
                "title": md_file.stem,
                "type": note_type,
                "score": hits,
                "content": content,
            })
        except Exception:
            continue

    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:max_results]

    return [
        {
            "title": n["title"],
            "type": n["type"],
            "excerpt": _extract_excerpt(n["content"], query_words),
        }
        for n in top
    ]


def _extract_excerpt(content: str, query_words: set, max_chars: int = 800) -> str:
    """Extract the most relevant paragraph from a note."""
    paragraphs = [p.strip() for p in content.split("\n\n") if len(p.strip()) > 50]
    if not paragraphs:
        return content[:max_chars]

    # Score paragraphs by query word density
    best = max(
        paragraphs,
        key=lambda p: sum(1 for w in query_words if w in p.lower()),
        default=paragraphs[0],
    )
    return best[:max_chars]


def _classify_note_type(path: Path) -> str:
    path_lower = str(path).lower()
    for note_type, keywords in NOTE_TYPE_MAP.items():
        if any(kw in path_lower for kw in keywords):
            return note_type
    return "general"


# ── Write: Genesis → vault ────────────────────────────────────────────────────

def write_postmortem_to_vault(
    incident_id: str,
    prompt: str,
    root_cause: Optional[str],
    resolution: Optional[str],
    confidence_score: float,
    step_log: list[str],
    notion_url: Optional[str] = None,
) -> Optional[Path]:
    """
    Write a post-mortem note to the Obsidian vault.

    The note is plain markdown, human-editable.
    Engineers can add corrections — Genesis reads them on the next investigation.

    The correction pattern (add this to any Genesis note to teach it):
        <!-- GENESIS_CORRECTION: The actual root cause was X, not Y -->
    """
    if not VAULT_PATH or not VAULT_PATH.exists():
        logger.debug("[Obsidian] Vault not configured — skipping write")
        return None

    target_dir = VAULT_PATH / GENESIS_FOLDER
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H%M")
    filename = f"{timestamp}_{incident_id[:8]}.md"
    filepath = target_dir / filename

    content = _build_postmortem_note(
        incident_id=incident_id,
        prompt=prompt,
        root_cause=root_cause,
        resolution=resolution,
        confidence_score=confidence_score,
        step_log=step_log,
        notion_url=notion_url,
    )

    try:
        filepath.write_text(content, encoding="utf-8")
        logger.info(f"[Obsidian] Post-mortem written: {filepath}")
        return filepath
    except Exception as exc:
        logger.warning(f"[Obsidian] Write failed: {exc}")
        return None


def _build_postmortem_note(
    incident_id: str,
    prompt: str,
    root_cause: Optional[str],
    resolution: Optional[str],
    confidence_score: float,
    step_log: list[str],
    notion_url: Optional[str],
) -> str:
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    confidence_pct = f"{confidence_score * 100:.0f}%"

    lines = [
        f"# Incident Post-Mortem — {timestamp}",
        "",
        "---",
        "",
        "## Metadata",
        f"- **Incident ID:** `{incident_id}`",
        f"- **Timestamp:** {timestamp}",
        f"- **Confidence:** {confidence_pct}",
        f"- **Notion:** {notion_url or 'Not published'}",
        f"- **Source:** Genesis Autonomous Agent",
        "",
        "---",
        "",
        "## Incident",
        "",
        prompt,
        "",
        "---",
        "",
        "## Root Cause",
        "",
        root_cause or "*Could not be determined*",
        "",
        "---",
        "",
        "## Resolution",
        "",
        resolution or "*No resolution applied*",
        "",
        "---",
        "",
        "## Investigation Timeline",
        "",
    ]

    for entry in step_log[-20:]:    # Last 20 steps
        lines.append(f"- {entry}")

    lines.extend([
        "",
        "---",
        "",
        "## Human Review",
        "",
        "*This section is for engineers to add corrections, context, or notes.*",
        "*Genesis will read this on future investigations.*",
        "",
        "<!-- GENESIS_CORRECTION: Replace this comment with any corrections to the root cause or resolution analysis -->",
        "",
        "### Tags",
        "- #genesis-postmortem",
        "- #incident",
        "",
    ])

    return "\n".join(lines)


# ── Read corrections ──────────────────────────────────────────────────────────

def read_human_corrections(vault_path: Optional[Path] = None) -> list[str]:
    """
    Scan all Genesis post-mortem notes for human corrections.
    Returns list of correction strings to inject into future investigations.
    This closes the human-AI memory refinement loop.
    """
    search_path = vault_path or (VAULT_PATH / GENESIS_FOLDER if VAULT_PATH else None)
    if not search_path or not search_path.exists():
        return []

    corrections = []
    pattern = re.compile(r'<!--\s*GENESIS_CORRECTION:\s*(.*?)\s*-->', re.DOTALL)

    for md_file in search_path.glob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
            matches = pattern.findall(content)
            for match in matches:
                correction = match.strip()
                # Skip the placeholder text
                if correction and "Replace this comment" not in correction:
                    corrections.append(f"[Human correction from {md_file.stem}]: {correction}")
        except Exception:
            continue

    if corrections:
        logger.info(f"[Obsidian] Found {len(corrections)} human corrections")

    return corrections


# ── Sync vault index to Supabase ──────────────────────────────────────────────

def sync_vault_to_db() -> int:
    """
    Index all vault .md files into the obsidian_sync Supabase table.
    Run on startup and whenever the vault changes.
    Returns count of newly indexed files.
    """
    if not VAULT_PATH or not VAULT_PATH.exists():
        return 0

    try:
        from core.memory_layers import _get_client
        client = _get_client()
        if not client:
            return 0
    except Exception:
        return 0

    synced = 0
    for md_file in VAULT_PATH.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
            file_hash = hashlib.sha256(content.encode()).hexdigest()
            rel_path = str(md_file.relative_to(VAULT_PATH))

            # Check if already synced with same hash
            existing = client.table("obsidian_sync").select("file_hash").eq("file_path", rel_path).execute()
            if existing.data and existing.data[0]["file_hash"] == file_hash:
                continue   # No change

            note_type = _classify_note_type(md_file)
            client.table("obsidian_sync").upsert({
                "file_path": rel_path,
                "file_hash": file_hash,
                "note_type": note_type,
                "synced_at": datetime.utcnow().isoformat(),
                "content_preview": content[:500],
            }).execute()
            synced += 1

        except Exception:
            continue

    if synced:
        logger.info(f"[Obsidian] Synced {synced} new/updated notes to Supabase")
    return synced
