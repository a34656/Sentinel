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

    PRIMARY_CLOUD: str = os.getenv("PRIMARY_CLOUD", "aws")

    # GCP
    GCP_PROJECT_ID: str = os.getenv("GCP_PROJECT_ID", "")
    GCP_REGION: str = os.getenv("GCP_REGION", "us-central1")
    GCP_SERVICE_ACCOUNT_PATH: str = os.getenv("GCP_SERVICE_ACCOUNT_PATH", "")

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
    MAX_SCRIPT_RETRIES: int = 5
    MAX_AGENT_ITERATIONS: int = 20

    # Confidence required before the agent attempts an automatic fix
    AUTO_FIX_CONFIDENCE_THRESHOLD: float = 0.85

    # ── Bayesian selector ─────────────────────────────────────────────────
    # Set to False to disable Bayesian hints (degrades to vanilla greedy master)
    BAYESIAN_SELECTOR_ENABLED: bool = os.getenv("BAYESIAN_SELECTOR_ENABLED", "true").lower() == "true"

    # ── Obsidian integration ──────────────────────────────────────────────
    OBSIDIAN_VAULT_PATH: str = os.getenv("OBSIDIAN_VAULT_PATH", "")
    OBSIDIAN_GENESIS_FOLDER: str = os.getenv("OBSIDIAN_GENESIS_FOLDER", "Genesis/PostMortems")
    OBSIDIAN_RUNBOOK_FOLDER: str = os.getenv("OBSIDIAN_RUNBOOK_FOLDER", "Runbooks")

    # ── Watchdog ──────────────────────────────────────────────────────────
    WATCHDOG_ENABLED: bool = os.getenv("WATCHDOG_ENABLED", "false").lower() == "true"
    WATCHDOG_INTERVAL_SECONDS: int = int(os.getenv("WATCHDOG_INTERVAL_SECONDS", "300"))  # 5 min default
    # Billing anomaly threshold (fraction above mean — 0.40 = 40% above)
    WATCHDOG_BILLING_THRESHOLD: float = float(os.getenv("WATCHDOG_BILLING_THRESHOLD", "0.40"))
    # Error spike threshold (multiplier above baseline — 3.0 = 3x normal errors)
    WATCHDOG_ERROR_THRESHOLD: float = float(os.getenv("WATCHDOG_ERROR_THRESHOLD", "3.0"))


config = Config()