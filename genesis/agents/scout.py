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


firecrawl = FirecrawlApp(api_key=config.FIRECRAWL_API_KEY) if config.FIRECRAWL_API_KEY else None

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
        content = (
            f"[Scout] Web search is unavailable ({exc}). "
            "The engineer agent should write self-contained scripts using only "
            "the MONGODB_URI and MONGODB_DB environment variables already injected. "
            "No additional documentation is needed — proceed with the MongoDB investigation."
        )

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
    if not firecrawl:
        return "[Scout] Firecrawl not configured — no API key"
    result = firecrawl.scrape_url(url, params={"formats": ["markdown"]})
    return result.get("markdown") or result.get("content") or "No content retrieved"


def _search(query: str) -> str:
    if not firecrawl:
        return (
            "[Scout] Firecrawl not configured. Engineer should use the pre-injected "
            "MONGODB_URI environment variable to connect and run queries directly."
        )
    try:
        results = firecrawl.search(query, params={"limit": 3})
    except Exception as exc:
        # Firecrawl v1 does not support search — return a helpful fallback
        if "not supported" in str(exc).lower() or "search" in str(exc).lower():
            return (
                "[Scout] Firecrawl search is not available in the current API version. "
                "The MongoDB connection string is already available as the MONGODB_URI env var. "
                "Proceed with writing a Python script that connects using that variable."
            )
        raise
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
