"""
scout.py — The Scout worker.

When the Master encounters an unfamiliar API, error code, or needs to read
current documentation, it delegates here. The Scout uses Firecrawl to either:
  - Scrape a specific URL (when Master provides one)
  - Search the web and return the top results (when Master provides a query)

The returned content is appended to documentation_context so the Master
can reference it in subsequent reasoning steps.
"""

import re

from firecrawl import FirecrawlApp
from loguru import logger

from core.state import AgentState
from core.config import config


firecrawl = FirecrawlApp(api_key=config.FIRECRAWL_API_KEY)

# Maximum chars to keep from any single crawl (avoid flooding the context window)
MAX_CONTENT_CHARS = 8_000


def crawl(state: AgentState) -> AgentState:
    instruction = state.get("_worker_instruction", "")
    logger.info(f"[Scout] Instruction: {instruction[:120]}")

    url = _extract_url(instruction)

    try:
        if url:
            content = _scrape_url(url)
        else:
            content = _search(instruction)
    except Exception as exc:
        logger.error(f"[Scout] Crawl failed: {exc}")
        content = f"[Scout crawl failed: {exc}]"

    # Truncate and append to existing context
    content = content[:MAX_CONTENT_CHARS]
    existing = state.get("documentation_context") or ""
    updated_context = existing + f"\n\n--- Scout result for: {url or instruction[:60]} ---\n\n" + content

    log_entry = f"[Scout] Retrieved {len(content)} chars of documentation"
    logger.info(log_entry)

    return {
        **state,
        "current_worker": "scout",
        "documentation_context": updated_context,
        "step_log": [log_entry],
    }


# ── Firecrawl helpers ─────────────────────────────────────────────────────────

def _scrape_url(url: str) -> str:
    result = firecrawl.scrape_url(url, params={"formats": ["markdown"]})
    return result.get("markdown") or result.get("content") or "No content retrieved"


def _search(query: str) -> str:
    results = firecrawl.search(query, params={"limit": 3})
    pages = []
    for item in (results.get("data") or []):
        title = item.get("title", "")
        body = item.get("markdown") or item.get("content") or ""
        if body:
            pages.append(f"### {title}\n{body[:2000]}")
    return "\n\n".join(pages) if pages else "No search results found"


def _extract_url(text: str) -> str | None:
    match = re.search(r'https?://\S+', text)
    return match.group().rstrip(".,)") if match else None
