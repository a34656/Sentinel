"""
agents/github_worker.py — GitHub Security Audit Worker.

Uses the GitHub REST API directly (no MCP server process needed, no local clone).
The Master delegates here when it needs to:

  - Read repository structure (file tree)
  - Read specific files by path
  - Search for patterns across the entire codebase (code search)
  - List dependency files (requirements.txt, package.json, go.mod, etc.)
  - Read recent commits and PR descriptions for change context
  - Scan for hardcoded secrets via regex patterns

All operations are READ-ONLY. The token should have repo:read scope only.
Write operations (push, merge, delete) are registered in config.BLOCKED_ACTIONS
and will be caught by policy_guard before they can execute.

Output format:
  All findings are written to state["github_context"] (str) — a structured
  markdown block the Master can reason over. Critical findings are also
  appended to state["corroborating_signals"] so confidence can be updated.
"""

import os
import re
import base64
import json
from typing import Optional
from urllib.parse import urlparse

import httpx
from loguru import logger

from core.state import AgentState
from core.config import config


# ── Constants ──────────────────────────────────────────────────────────────────

# Maximum file size to read in full (bytes). Larger files get truncated.
MAX_FILE_BYTES = 50_000

# How many files to scan for secrets (avoid huge repos timing out)
MAX_SECRET_SCAN_FILES = 200

# Secret patterns — (label, compiled regex)
SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("AWS Access Key",            re.compile(r'AKIA[0-9A-Z]{16}', re.IGNORECASE)),
    ("AWS Secret Key",            re.compile(r'(?i)aws.{0,20}secret.{0,20}[\'"][0-9a-zA-Z/+]{40}[\'"]')),
    ("GCP API Key",               re.compile(r'AIza[0-9A-Za-z\-_]{35}')),
    ("GitHub Token",              re.compile(r'gh[pousr]_[0-9a-zA-Z]{36,}')),
    ("Stripe Secret Key",         re.compile(r'sk_(live|test)_[0-9a-zA-Z]{24,}')),
    ("Slack Token",               re.compile(r'xox[baprs]-[0-9a-zA-Z\-]+')),
    ("Generic API Key",           re.compile(r'(?i)(api[_\-]?key|apikey)\s*[=:]\s*[\'"]([^\'"\s]{20,})[\'"]')),
    ("Generic Secret",            re.compile(r'(?i)(secret[_\-]?key|secret)\s*[=:]\s*[\'"]([^\'"\s]{12,})[\'"]')),
    ("Generic Password",          re.compile(r'(?i)(password|passwd|pwd)\s*[=:]\s*[\'"]([^\'"\s]{8,})[\'"]')),
    ("Private Key Header",        re.compile(r'-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----')),
    ("Database Connection String",re.compile(r'(?i)(postgres|mysql|mongodb)://[^\s\'"]+')),
    ("JWT Secret",                re.compile(r'(?i)jwt.{0,15}secret.{0,5}[\'"][0-9a-zA-Z+/=_\-]{20,}[\'"]')),
    ("Bearer Token Hardcoded",    re.compile(r'(?i)bearer\s+[0-9a-zA-Z\._\-]{20,}')),
    ("Twilio Token",              re.compile(r'SK[0-9a-f]{32}')),
    ("SendGrid Key",              re.compile(r'SG\.[0-9a-zA-Z\-_]{22}\.[0-9a-zA-Z\-_]{43}')),
]

# Files to skip during secret scanning (binary, generated, vendor)
SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2",
    ".ttf", ".eot", ".pdf", ".zip", ".tar", ".gz", ".lock", ".sum",
    ".min.js", ".min.css", ".map",
}

# Dependency manifest files we look for
DEPENDENCY_FILES = [
    "requirements.txt", "requirements-dev.txt", "requirements-prod.txt",
    "Pipfile", "Pipfile.lock",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "go.mod", "go.sum",
    "Cargo.toml", "Cargo.lock",
    "pom.xml", "build.gradle", "build.gradle.kts",
    "Gemfile", "Gemfile.lock",
    "composer.json", "composer.lock",
    "pyproject.toml", "setup.py", "setup.cfg",
    ".github/dependabot.yml",
]


# ── Main worker function ───────────────────────────────────────────────────────

def audit(state: AgentState) -> AgentState:
    """
    Entry point called by LangGraph. Parses the Master's instruction to decide
    which GitHub operations to perform, executes them, and returns updated state.
    """
    instruction = state.get("_worker_instruction", "")
    incident    = state.get("incident_prompt", "")
    logger.info(f"[GitHub] Instruction: {instruction[:120]}")

    # Extract repo URL from instruction or incident prompt
    repo_url = _extract_repo_url(instruction) or _extract_repo_url(incident)
    if not repo_url:
        msg = "[GitHub] ❌ No GitHub repository URL found in instruction or incident prompt."
        logger.error(msg)
        return {**state, "current_worker": "github_worker", "step_log": [msg]}

    owner, repo = _parse_repo(repo_url)
    if not owner or not repo:
        msg = f"[GitHub] ❌ Could not parse owner/repo from URL: {repo_url}"
        logger.error(msg)
        return {**state, "current_worker": "github_worker", "step_log": [msg]}

    logger.info(f"[GitHub] Auditing {owner}/{repo}")
    client = _make_client()

    sections: list[str] = []
    new_signals: list[str] = []
    log_entries: list[str] = []
    instruction_lower = instruction.lower()

    # ── 1. Repository overview ─────────────────────────────────────────────
    repo_info = _get_repo_info(client, owner, repo)
    sections.append(_format_repo_overview(repo_info, owner, repo))
    log_entries.append(f"[GitHub] 📦 Repo: {owner}/{repo} — {repo_info.get('description', 'no description')}")

    # ── 2. File tree ───────────────────────────────────────────────────────
    tree = _get_file_tree(client, owner, repo)
    sections.append(_format_tree(tree))
    log_entries.append(f"[GitHub] 🗂 File tree: {len(tree)} items")

    # ── 3. Dependency files ────────────────────────────────────────────────
    dep_findings = _read_dependency_files(client, owner, repo, tree)
    if dep_findings:
        sections.append(dep_findings["section"])
        log_entries.append(f"[GitHub] 📦 Dependencies: found {dep_findings['file_count']} manifest file(s)")
        if dep_findings.get("signals"):
            new_signals.extend(dep_findings["signals"])

    # ── 4. Secret scan ────────────────────────────────────────────────────
    if any(kw in instruction_lower for kw in [
        "secret", "credential", "hardcoded", "token", "key", "password", "security", "audit", "all"
    ]):
        secret_findings = _scan_for_secrets(client, owner, repo, tree)
        sections.append(secret_findings["section"])
        log_entries.append(f"[GitHub] 🔑 Secret scan: {secret_findings['hit_count']} potential findings in {secret_findings['files_scanned']} files")
        if secret_findings.get("signals"):
            new_signals.extend(secret_findings["signals"])

    # ── 5. Specific file reads ─────────────────────────────────────────────
    file_paths = _extract_file_paths(instruction)
    for path in file_paths[:5]:  # cap at 5 explicit reads per step
        content = _read_file(client, owner, repo, path)
        sections.append(f"## File: `{path}`\n\n```\n{content[:3000]}\n```")
        log_entries.append(f"[GitHub] 📄 Read: {path}")

    # ── 6. Recent commits ─────────────────────────────────────────────────
    if any(kw in instruction_lower for kw in ["commit", "change", "recent", "history", "pr", "pull request"]):
        commits_section = _get_recent_commits(client, owner, repo)
        sections.append(commits_section)
        log_entries.append("[GitHub] 📝 Recent commits retrieved")

    # ── 7. Code search ────────────────────────────────────────────────────
    search_query = _extract_search_query(instruction)
    if search_query:
        search_results = _search_code(client, owner, repo, search_query)
        sections.append(search_results)
        log_entries.append(f"[GitHub] 🔍 Code search: '{search_query[:50]}'")

    # ── Assemble context block ─────────────────────────────────────────────
    context_block = f"# GitHub Security Audit — {owner}/{repo}\n\n" + "\n\n---\n\n".join(sections)

    # Append to existing documentation_context
    existing_docs = state.get("documentation_context") or ""
    updated_docs  = existing_docs + f"\n\n{context_block}"

    # Also store in dedicated github_context field
    existing_github = state.get("github_context") or ""
    updated_github  = existing_github + f"\n\n{context_block}"

    combined_signals = list(state.get("corroborating_signals", [])) + new_signals

    for entry in log_entries:
        logger.info(entry)

    return {
        **state,
        "current_worker":         "github_worker",
        "documentation_context":  updated_docs,
        "github_context":         updated_github,
        "corroborating_signals":  combined_signals,
        "step_log":               log_entries,
    }


# ── GitHub API helpers ─────────────────────────────────────────────────────────

def _make_client() -> httpx.Client:
    token = config.GITHUB_TOKEN
    headers = {
        "Accept":               "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(
        base_url="https://api.github.com",
        headers=headers,
        timeout=20.0,
    )


def _get_repo_info(client: httpx.Client, owner: str, repo: str) -> dict:
    try:
        r = client.get(f"/repos/{owner}/{repo}")
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning(f"[GitHub] repo info failed: {exc}")
        return {}


def _get_file_tree(client: httpx.Client, owner: str, repo: str, branch: str = "HEAD") -> list[dict]:
    """Recursively fetch the full file tree using the Git Trees API."""
    try:
        r = client.get(f"/repos/{owner}/{repo}/git/trees/{branch}?recursive=1")
        r.raise_for_status()
        data = r.json()
        return data.get("tree", [])
    except Exception as exc:
        logger.warning(f"[GitHub] file tree failed: {exc}")
        return []


def _read_file(client: httpx.Client, owner: str, repo: str, path: str) -> str:
    """Read a single file's content via the Contents API."""
    try:
        r = client.get(f"/repos/{owner}/{repo}/contents/{path}")
        r.raise_for_status()
        data = r.json()

        if data.get("encoding") == "base64":
            raw = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            return raw[:MAX_FILE_BYTES]

        return data.get("content", "")[:MAX_FILE_BYTES]
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return f"[File not found: {path}]"
        return f"[Read error {exc.response.status_code}: {path}]"
    except Exception as exc:
        return f"[Read error: {exc}]"


def _search_code(client: httpx.Client, owner: str, repo: str, query: str) -> str:
    """Use GitHub Code Search API to find patterns in the repo."""
    try:
        q = f"{query} repo:{owner}/{repo}"
        r = client.get("/search/code", params={"q": q, "per_page": 10})
        r.raise_for_status()
        items = r.json().get("items", [])
        if not items:
            return f"## Code Search: `{query}`\n\nNo results found."

        lines = [f"## Code Search: `{query}`\n\nFound {len(items)} match(es):\n"]
        for item in items:
            file_path = item.get("path", "")
            url       = item.get("html_url", "")
            lines.append(f"- [`{file_path}`]({url})")
        return "\n".join(lines)
    except Exception as exc:
        return f"## Code Search\n\n[Search failed: {exc}]"


def _get_recent_commits(client: httpx.Client, owner: str, repo: str, count: int = 10) -> str:
    """Fetch the last N commits."""
    try:
        r = client.get(f"/repos/{owner}/{repo}/commits", params={"per_page": count})
        r.raise_for_status()
        commits = r.json()
        lines = ["## Recent Commits\n"]
        for c in commits:
            sha   = c.get("sha", "")[:8]
            msg   = c.get("commit", {}).get("message", "").split("\n")[0][:100]
            author = c.get("commit", {}).get("author", {}).get("name", "unknown")
            date   = c.get("commit", {}).get("author", {}).get("date", "")[:10]
            lines.append(f"- `{sha}` {date} **{author}**: {msg}")
        return "\n".join(lines)
    except Exception as exc:
        return f"## Recent Commits\n\n[Failed: {exc}]"


# ── Dependency reading ─────────────────────────────────────────────────────────

def _read_dependency_files(
    client: httpx.Client, owner: str, repo: str, tree: list[dict]
) -> Optional[dict]:
    """Find and read all dependency manifest files in the repo."""
    tree_paths = {item["path"] for item in tree if item.get("type") == "blob"}

    found_files: list[tuple[str, str]] = []  # (path, content)
    for dep_file in DEPENDENCY_FILES:
        # Exact match
        if dep_file in tree_paths:
            content = _read_file(client, owner, repo, dep_file)
            found_files.append((dep_file, content))
        else:
            # Subdirectory match (e.g. backend/requirements.txt)
            matches = [p for p in tree_paths if p.endswith(f"/{dep_file}") or p == dep_file]
            for match in matches[:2]:
                content = _read_file(client, owner, repo, match)
                found_files.append((match, content))

    if not found_files:
        return None

    sections = ["## Dependency Files\n"]
    signals  = []

    for path, content in found_files:
        sections.append(f"### `{path}`\n\n```\n{content[:2000]}\n```")

        # Flag if Pipfile.lock or package-lock.json is missing (indicates no lock file)
        if path == "requirements.txt" and "requirements.txt" in tree_paths:
            lock_present = any(
                p for p in tree_paths
                if p in ("Pipfile.lock", "poetry.lock", "requirements-frozen.txt")
            )
            if not lock_present:
                signals.append("No Python lock file found — dependency versions are unpinned")

    return {
        "section":    "\n\n".join(sections),
        "file_count": len(found_files),
        "signals":    signals,
    }


# ── Secret scanning ────────────────────────────────────────────────────────────

def _scan_for_secrets(
    client: httpx.Client, owner: str, repo: str, tree: list[dict]
) -> dict:
    """
    Scan every text file in the repo for hardcoded secret patterns.
    Uses the Contents API — no local clone needed.
    """
    blob_files = [
        item["path"] for item in tree
        if item.get("type") == "blob"
        and not any(item["path"].endswith(ext) for ext in SKIP_EXTENSIONS)
        and not any(seg in item["path"] for seg in [
            "node_modules/", ".git/", "vendor/", "dist/", "build/", "__pycache__/"
        ])
    ][:MAX_SECRET_SCAN_FILES]

    findings: list[dict] = []
    files_scanned = 0

    for path in blob_files:
        content = _read_file(client, owner, repo, path)
        if content.startswith("["):
            continue  # skip error strings
        files_scanned += 1

        for label, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(content):
                matched_text = match.group()
                # Redact most of the value for safety
                display = matched_text[:6] + "..." + matched_text[-3:] if len(matched_text) > 12 else "***"
                # Find line number
                line_no = content[:match.start()].count("\n") + 1
                findings.append({
                    "type":    label,
                    "file":    path,
                    "line":    line_no,
                    "preview": display,
                })

    # De-duplicate (same file + type combo)
    seen: set = set()
    unique_findings: list[dict] = []
    for f in findings:
        key = (f["file"], f["type"])
        if key not in seen:
            seen.add(key)
            unique_findings.append(f)

    # Format section
    lines = [f"## Hardcoded Secret Scan\n\nScanned {files_scanned} files. Found **{len(unique_findings)}** potential issue(s).\n"]

    if unique_findings:
        lines.append("| Severity | Type | File | Line | Preview |")
        lines.append("|----------|------|------|------|---------|")
        for f in unique_findings[:50]:  # cap display at 50
            severity = "🔴 CRITICAL" if any(
                kw in f["type"] for kw in ["AWS", "GCP", "Private Key", "Stripe"]
            ) else "🟡 HIGH"
            lines.append(f"| {severity} | {f['type']} | `{f['file']}` | {f['line']} | `{f['preview']}` |")
    else:
        lines.append("✅ No hardcoded secrets detected.")

    signals: list[str] = []
    if unique_findings:
        critical = [f for f in unique_findings if any(
            kw in f["type"] for kw in ["AWS", "GCP", "Private Key", "Stripe"]
        )]
        if critical:
            signals.append(f"🔴 {len(critical)} CRITICAL hardcoded credential(s) found in source code")
        signals.append(f"🟡 {len(unique_findings)} potential secret(s) detected across {files_scanned} files")

    return {
        "section":       "\n".join(lines),
        "hit_count":     len(unique_findings),
        "files_scanned": files_scanned,
        "signals":       signals,
    }


# ── Formatting helpers ─────────────────────────────────────────────────────────

def _format_repo_overview(info: dict, owner: str, repo: str) -> str:
    if not info:
        return f"## Repository: {owner}/{repo}\n\n[Could not retrieve repo metadata]"

    lines = [
        f"## Repository: {owner}/{repo}",
        "",
        f"**Description:** {info.get('description') or 'None'}",
        f"**Language:**     {info.get('language') or 'Unknown'}",
        f"**Stars:**        {info.get('stargazers_count', 0):,}",
        f"**Forks:**        {info.get('forks_count', 0):,}",
        f"**Open Issues:**  {info.get('open_issues_count', 0)}",
        f"**Default Branch:** `{info.get('default_branch', 'main')}`",
        f"**Visibility:**   {info.get('visibility', 'unknown')}",
        f"**Last Push:**    {info.get('pushed_at', 'unknown')[:10]}",
    ]

    # Security flags
    flags: list[str] = []
    if not info.get("private"):
        flags.append("⚠️  Public repository — any secrets found are publicly exposed")
    if info.get("has_wiki"):
        flags.append("ℹ️  Wiki enabled")
    if not info.get("has_issues"):
        flags.append("ℹ️  Issues disabled")

    if flags:
        lines.append("")
        lines.extend(flags)

    return "\n".join(lines)


def _format_tree(tree: list[dict]) -> str:
    if not tree:
        return "## File Tree\n\n[Empty or inaccessible]"

    # Show top-level structure only (avoid overwhelming the context)
    blobs = [item["path"] for item in tree if item.get("type") == "blob"]
    dirs  = sorted(set(
        p.split("/")[0] for p in blobs if "/" in p
    ))

    lines = [f"## File Tree ({len(blobs)} files)\n"]
    # Top-level files
    top_files = [p for p in blobs if "/" not in p]
    for f in top_files:
        lines.append(f"  {f}")
    # Directories
    for d in dirs:
        count = sum(1 for p in blobs if p.startswith(f"{d}/"))
        lines.append(f"  {d}/  ({count} files)")

    return "\n".join(lines)


# ── Parse helpers ──────────────────────────────────────────────────────────────

def _extract_repo_url(text: str) -> Optional[str]:
    """Extract a GitHub repository URL from free text."""
    match = re.search(r'https://github\.com/([^/\s]+)/([^/\s\'"]+)', text)
    return match.group(0).rstrip(".,)") if match else None


def _parse_repo(url: str) -> tuple[str, str]:
    """Return (owner, repo) from a GitHub URL."""
    try:
        parts = urlparse(url).path.strip("/").split("/")
        if len(parts) >= 2:
            return parts[0], parts[1].replace(".git", "")
    except Exception:
        pass
    return "", ""


def _extract_file_paths(instruction: str) -> list[str]:
    """Extract explicit file paths the Master wants read."""
    # Match quoted paths or paths starting with common separators
    matches = re.findall(r'[\'"`]([a-zA-Z0-9_\-./]+\.[a-zA-Z]{1,6})[\'"`]', instruction)
    return matches


def _extract_search_query(instruction: str) -> Optional[str]:
    """Extract a code search query from the instruction."""
    match = re.search(
        r'(?:search for|find pattern|grep for|look for)\s+[\'"`]?([^\'"`\n]{5,80})[\'"`]?',
        instruction,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else None
