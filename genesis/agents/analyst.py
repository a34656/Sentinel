"""
analyst.py — The Analyst worker.

Pulls structured observability data from AWS or GCP based on filters
the Master specifies in its instruction. Returns raw structured data only —
interpretation is exclusively the Master's job.

Supported data sources:
  - AWS Cost Explorer  (billing anomalies)
  - AWS CloudWatch     (logs, metrics)
"""

import json
from datetime import datetime, timedelta

import boto3
from loguru import logger

from core.state import AgentState
from core.config import config


def pull_data(state: AgentState) -> AgentState:
    instruction = state.get("_worker_instruction", "").lower()
    logger.info(f"[Analyst] Instruction: {instruction[:120]}")

    data = {}

    if "cost" in instruction or "billing" in instruction or "spend" in instruction:
        data["cost_explorer"] = _pull_cost_explorer(days=14)

    if "log" in instruction or "error" in instruction or "cloudwatch" in instruction:
        log_group = _extract_log_group(instruction)
        data["cloudwatch_logs"] = _pull_cloudwatch_logs(log_group)

    if not data:
        # Default: pull cost data — most common use case
        data["cost_explorer"] = _pull_cost_explorer(days=7)

    log_entry = f"[Analyst] Pulled data: {list(data.keys())} ({sum(len(str(v)) for v in data.values())} chars total)"
    logger.info(log_entry)

    return {
        **state,
        "current_worker": "analyst",
        "raw_cost_data": data,
        "step_log": [log_entry],
    }


# ── AWS Cost Explorer ─────────────────────────────────────────────────────────

def _pull_cost_explorer(days: int = 14) -> dict:
    """Pull daily costs broken down by service for the last N days."""
    try:
        client = boto3.client("ce", region_name=config.AWS_REGION)
        end = datetime.utcnow().date()
        start = end - timedelta(days=days)

        response = client.get_cost_and_usage(
            TimePeriod={"Start": str(start), "End": str(end)},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )

        # Flatten to a simpler structure the Master can reason about
        daily_costs = []
        for result in response.get("ResultsByTime", []):
            day = result["TimePeriod"]["Start"]
            services = {
                group["Keys"][0]: float(group["Metrics"]["UnblendedCost"]["Amount"])
                for group in result.get("Groups", [])
            }
            daily_costs.append({"date": day, "services": services})

        return {"daily_costs": daily_costs, "period_days": days}

    except Exception as exc:
        logger.error(f"[Analyst] Cost Explorer error: {exc}")
        return {"error": str(exc)}


# ── AWS CloudWatch Logs ───────────────────────────────────────────────────────

def _pull_cloudwatch_logs(log_group: str, hours: int = 3) -> dict:
    """Pull the most recent error/warning log events from a CloudWatch log group."""
    try:
        client = boto3.client("logs", region_name=config.AWS_REGION)
        end_ms = int(datetime.utcnow().timestamp() * 1000)
        start_ms = end_ms - (hours * 3600 * 1000)

        # Search for errors specifically
        response = client.filter_log_events(
            logGroupName=log_group,
            startTime=start_ms,
            endTime=end_ms,
            filterPattern="?ERROR ?error ?Exception ?exception ?FATAL",
            limit=100,
        )

        events = [
            {
                "timestamp": e["timestamp"],
                "message": e["message"][:500],  # Truncate long lines
            }
            for e in response.get("events", [])
        ]

        return {"log_group": log_group, "events": events, "count": len(events)}

    except Exception as exc:
        logger.error(f"[Analyst] CloudWatch error: {exc}")
        return {"error": str(exc), "log_group": log_group}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_log_group(instruction: str) -> str:
    """
    Try to extract a log group name from the Master's instruction.
    Falls back to a sensible default.
    """
    import re
    # Match patterns like /aws/lambda/my-function or /ecs/my-service
    match = re.search(r'(/[a-zA-Z0-9/_-]{3,})', instruction)
    if match:
        return match.group(1)
    return "/aws/lambda/production"  # Sensible default
