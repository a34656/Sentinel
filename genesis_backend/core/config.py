import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── LLM ──────────────────────────────────────────────────────────────
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = "gemini-2.5-flash-lite"

    # ── Sandbox ───────────────────────────────────────────────────────────
    E2B_API_KEY: str = os.getenv("E2B_API_KEY", "")

    # ── Web Research ──────────────────────────────────────────────────────
    FIRECRAWL_API_KEY: str = os.getenv("FIRECRAWL_API_KEY", "")

    # ── Notion ────────────────────────────────────────────────────────────
    NOTION_API_KEY: str = os.getenv("NOTION_API_KEY", "")
    NOTION_DATABASE_ID: str = os.getenv("NOTION_DATABASE_ID", "")

    # ── Supabase ──────────────────────────────────────────────────────────
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

    # ── AWS ───────────────────────────────────────────────────────────────
    AWS_REGION: str = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

    # ── Safety policy ─────────────────────────────────────────────────────
    # Any proposed fix containing these strings is blocked for human approval
    BLOCKED_ACTIONS: list[str] = [
        "terminate_instance",
        "delete_bucket",
        "drop_database",
        "revoke_iam_policy",
        "disable_service",
        "delete_table",
        "purge_queue",
    ]

    # ── Retry / iteration limits ──────────────────────────────────────────
    MAX_SCRIPT_RETRIES: int = 3
    MAX_AGENT_ITERATIONS: int = 20

    # Confidence required before the agent attempts an automatic fix
    AUTO_FIX_CONFIDENCE_THRESHOLD: float = 0.85


config = Config()