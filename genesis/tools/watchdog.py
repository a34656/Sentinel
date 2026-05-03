"""
tools/watchdog.py — Tiered Continuous Monitoring

Solves the token cost problem for 24/7 monitoring.

Tier 1 — Dumb threshold checks (pure Python, zero LLM cost)
    Runs every 5 minutes via APScheduler or external cron.
    Checks if any metric exceeds a learned baseline threshold.
    Cost: essentially free — just AWS API calls.

Tier 2 — Lightweight classifier (Gemini Flash, ~500 tokens)
    Triggers only when Tier 1 flags an anomaly.
    Asks: "Is this worth a full investigation?"
    Expected frequency: ~10-20x per day in a normal system.
    Cost: ~$0.01/day.

Tier 3 — Full Genesis investigation (Gemini Pro / Claude Sonnet)
    Triggers only when Tier 2 says yes.
    Expected frequency: 1-3x per day in a healthy system.
    Cost: ~$0.30-0.45/day.

This gives you 24/7 monitoring for under $1/day per monitored system.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Optional

import boto3
from loguru import logger

from core.config import config


# ── Baseline store ────────────────────────────────────────────────────────────
# Learned baselines persisted as JSON. In production: move to Supabase.
# Format: { "metric_key": { "mean": float, "std": float, "last_updated": str } }

BASELINE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "baselines.json")


def _load_baselines() -> dict:
    os.makedirs(os.path.dirname(BASELINE_PATH), exist_ok=True)
    if os.path.exists(BASELINE_PATH):
        try:
            with open(BASELINE_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_baselines(baselines: dict) -> None:
    os.makedirs(os.path.dirname(BASELINE_PATH), exist_ok=True)
    with open(BASELINE_PATH, "w") as f:
        json.dump(baselines, f, indent=2)


# ── Tier 1: Threshold checks ──────────────────────────────────────────────────

class WatchdogAlert:
    def __init__(self, metric: str, current: float, baseline: float, severity: str, description: str):
        self.metric = metric
        self.current = current
        self.baseline = baseline
        self.severity = severity        # "low" | "medium" | "high"
        self.description = description
        self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "current": self.current,
            "baseline": self.baseline,
            "deviation_pct": round((self.current - self.baseline) / max(self.baseline, 0.01) * 100, 1),
            "severity": self.severity,
            "description": self.description,
            "timestamp": self.timestamp,
        }


def run_tier1_checks() -> list[WatchdogAlert]:
    """
    Run all Tier 1 threshold checks. Returns list of alerts.
    No LLM involved. Pure API calls + threshold math.
    """
    alerts = []
    baselines = _load_baselines()

    alerts.extend(_check_billing(baselines))
    alerts.extend(_check_cloudwatch_errors(baselines))

    # Update baselines with today's data
    _save_baselines(baselines)

    if alerts:
        logger.info(f"[Watchdog Tier1] {len(alerts)} alert(s) detected")
    else:
        logger.debug("[Watchdog Tier1] All metrics within baseline")

    return alerts


def _check_billing(baselines: dict) -> list[WatchdogAlert]:
    """Check if today's AWS spend is anomalously high vs the 7-day baseline."""
    alerts = []
    try:
        client = boto3.client("ce", region_name=config.AWS_REGION)
        today = datetime.utcnow().date()
        yesterday = today - timedelta(days=1)
        week_ago = today - timedelta(days=8)

        response = client.get_cost_and_usage(
            TimePeriod={"Start": str(week_ago), "End": str(today)},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
        )

        daily_costs = []
        for result in response.get("ResultsByTime", []):
            cost = float(result["Total"]["UnblendedCost"]["Amount"])
            daily_costs.append(cost)

        if len(daily_costs) < 2:
            return alerts

        # Yesterday's cost vs 7-day mean (excluding yesterday)
        historical = daily_costs[:-1]
        mean_cost = sum(historical) / len(historical)
        yesterday_cost = daily_costs[-1]

        # Update baseline
        baselines["daily_billing"] = {
            "mean": round(mean_cost, 4),
            "last_updated": datetime.utcnow().isoformat(),
        }

        # Alert if yesterday was >25% above mean
        deviation = (yesterday_cost - mean_cost) / max(mean_cost, 0.01)
        if deviation > 0.40:
            alerts.append(WatchdogAlert(
                metric="daily_billing",
                current=yesterday_cost,
                baseline=mean_cost,
                severity="high" if deviation > 0.75 else "medium",
                description=f"AWS daily spend ${yesterday_cost:.2f} is {deviation*100:.0f}% above 7-day mean ${mean_cost:.2f}",
            ))

    except Exception as exc:
        logger.warning(f"[Watchdog] Billing check failed: {exc}")

    return alerts


def _check_cloudwatch_errors(baselines: dict) -> list[WatchdogAlert]:
    """Check CloudWatch for spike in error-level log events."""
    alerts = []
    try:
        client = boto3.client("logs", region_name=config.AWS_REGION)
        now = datetime.utcnow()
        one_hour_ago = now - timedelta(hours=1)
        two_hours_ago = now - timedelta(hours=2)

        # Get all log groups (in production: filter to your monitored groups)
        groups_response = client.describe_log_groups(limit=10)
        log_groups = [g["logGroupName"] for g in groups_response.get("logGroups", [])]

        for log_group in log_groups[:3]:   # Check top 3 groups
            try:
                # Count errors in last hour vs previous hour
                current_count = _count_errors(client, log_group, one_hour_ago, now)
                previous_count = _count_errors(client, log_group, two_hours_ago, one_hour_ago)

                baseline_key = f"errors_{log_group.replace('/', '_')}"
                baseline_count = baselines.get(baseline_key, {}).get("mean", max(previous_count, 1))

                baselines[baseline_key] = {
                    "mean": (baseline_count * 0.9 + current_count * 0.1),   # Exponential moving average
                    "last_updated": now.isoformat(),
                }

                # Alert if current errors are 3x the baseline
                if current_count > max(baseline_count * 3, 10):
                    alerts.append(WatchdogAlert(
                        metric=f"cloudwatch_errors:{log_group}",
                        current=current_count,
                        baseline=baseline_count,
                        severity="high" if current_count > baseline_count * 5 else "medium",
                        description=f"{log_group}: {current_count} errors in last hour vs baseline {baseline_count:.0f}",
                    ))
            except Exception:
                pass   # Skip inaccessible log groups silently

    except Exception as exc:
        logger.warning(f"[Watchdog] CloudWatch check failed: {exc}")

    return alerts


def _count_errors(client, log_group: str, start: datetime, end: datetime) -> int:
    try:
        response = client.filter_log_events(
            logGroupName=log_group,
            startTime=int(start.timestamp() * 1000),
            endTime=int(end.timestamp() * 1000),
            filterPattern="?ERROR ?FATAL ?Exception ?exception",
            limit=100,
        )
        return len(response.get("events", []))
    except Exception:
        return 0


# ── Tier 2: LLM classifier ────────────────────────────────────────────────────

def run_tier2_classification(alerts: list[WatchdogAlert]) -> Optional[str]:
    """
    Ask a cheap LLM (Gemini Flash Lite): "Is this alert worth a full investigation?"
    Returns a prompt for the full Genesis investigation if yes, None if no.

    Called only when Tier 1 returns alerts.
    Cost: ~500 tokens per call, ~$0.0004.
    """
    if not alerts:
        return None

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import SystemMessage, HumanMessage

        classifier = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash-lite",
            google_api_key=config.GEMINI_API_KEY,
            temperature=0,
        )

        alert_descriptions = "\n".join(f"- {a.description} (severity: {a.severity})" for a in alerts)

        response = classifier.invoke([
            SystemMessage(content="""You are a triage classifier for infrastructure alerts.
Given a list of anomaly alerts, decide if they warrant a full autonomous investigation.

Respond with valid JSON only:
{
  "investigate": true | false,
  "reason": "one sentence",
  "prompt": "if investigate=true: the investigation prompt for the full agent, else null"
}

Investigate if: severity is high, multiple alerts correlate, or anomaly is >50% above baseline.
Do NOT investigate if: known scheduled jobs, minor fluctuations <25%, or single isolated low-severity alert."""),
            HumanMessage(content=f"Alerts detected:\n{alert_descriptions}"),
        ])

        import re, json as _json
        text = response.content
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            parsed = _json.loads(match.group())
            if parsed.get("investigate"):
                logger.info(f"[Watchdog Tier2] Full investigation triggered: {parsed.get('reason')}")
                return parsed.get("prompt")
            else:
                logger.info(f"[Watchdog Tier2] Alert suppressed: {parsed.get('reason')}")
                return None

    except Exception as exc:
        logger.warning(f"[Watchdog Tier2] Classification failed: {exc}")
        # Fail open: if classifier fails, trigger investigation for high-severity alerts
        if any(a.severity == "high" for a in alerts):
            return f"Automated detection: {alerts[0].description}"

    return None


# ── Full watchdog cycle ───────────────────────────────────────────────────────

async def run_watchdog_cycle(trigger_investigation_fn) -> Optional[str]:
    """
    Run one full watchdog cycle: Tier 1 → Tier 2 → Tier 3 trigger.

    trigger_investigation_fn: async callable that accepts a prompt string
    and starts a full Genesis investigation (calls POST /api/incident internally).

    Returns the investigation prompt if one was triggered, None otherwise.
    """
    logger.debug("[Watchdog] Starting cycle...")

    # Tier 1
    alerts = run_tier1_checks()
    if not alerts:
        return None

    # Tier 2
    investigation_prompt = run_tier2_classification(alerts)
    if not investigation_prompt:
        return None

    # Tier 3 — trigger full Genesis
    logger.info(f"[Watchdog] Triggering full investigation: {investigation_prompt[:100]}")
    await trigger_investigation_fn(investigation_prompt)
    return investigation_prompt
