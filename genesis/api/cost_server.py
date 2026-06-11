"""
api/cost_server.py
------------------
FastAPI SSE endpoint for the Cloud Cost Optimization agent.
Mirrors api/server.py from Genesis — same event format, same streaming pattern.

Events emitted (same schema as Genesis):
    GENESIS_THINKING      — Gemini reasoning step
    GENESIS_EXECUTING     — E2B script execution
    GENESIS_OUTPUT        — execution result preview
    GENESIS_BELIEF_UPDATE — Bayesian waste belief state
    GENESIS_FINDING       — confirmed waste finding
    GENESIS_COMPLETE      — investigation done
    GENESIS_REPORT_READY  — PDF available for download
    GENESIS_ERROR         — unrecoverable error
"""

import os
import json
import asyncio
import traceback
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.cost_state import CostAgentState
from core.cost_graph import cost_app
from agents.cost_master import INITIAL_BELIEFS

app = FastAPI(title="Genesis Cost Optimization Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── request/response models ───────────────────────────────────────────────────

class InvestigateRequest(BaseModel):
    prompt: str


# ── SSE helper ────────────────────────────────────────────────────────────────

def sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, 'payload': data, 'timestamp': datetime.utcnow().isoformat()})}\n\n"


# ── main investigation endpoint ───────────────────────────────────────────────

@app.post("/api/cost/investigate")
async def investigate(req: InvestigateRequest):
    """
    Stream a full cost investigation as SSE events.
    Drop-in replacement for /api/investigate in the main Genesis server.
    """
    async def event_stream():
        yield sse("GENESIS_THINKING", {
            "message": "Genesis Cost Agent initializing...",
            "iteration": 0,
        })

        initial_state: CostAgentState = {
            "incident_prompt": req.prompt,
            "iteration":       0,
            "phase":           "schema_inspection",
            "scripts":         [],
            "executed_scripts":[],
            "last_output":     "",
            "output_history":  [],
            "findings":        [],
            "waste_beliefs":   INITIAL_BELIEFS.copy(),
            "last_reasoning":  "",
            "report_path":     None,
        }

        try:
            async for event in cost_app.astream(
                initial_state,
                config={"recursion_limit": 100},
            ):
                node_name = list(event.keys())[0]
                state     = event[node_name]

                # ── master node events ────────────────────────────────────────
                if node_name == "master":
                    reasoning = state.get("last_reasoning", "")
                    iteration = state.get("iteration", 0)
                    beliefs   = state.get("waste_beliefs", {})

                    if reasoning:
                        yield sse("GENESIS_THINKING", {
                            "message":   reasoning[:500],
                            "iteration": iteration,
                        })

                    if beliefs:
                        yield sse("GENESIS_BELIEF_UPDATE", {
                            "beliefs":   beliefs,
                            "iteration": iteration,
                        })

                # ── engineer node events ──────────────────────────────────────
                elif node_name == "engineer":
                    last_output = state.get("last_output", "")
                    iteration   = state.get("iteration", 0)
                    findings    = state.get("findings", [])

                    yield sse("GENESIS_EXECUTING", {
                        "message":   f"Executing script (iteration {iteration})",
                        "iteration": iteration,
                    })

                    if last_output:
                        yield sse("GENESIS_OUTPUT", {
                            "output":    last_output[:1000],
                            "iteration": iteration,
                        })

                    # Emit any new findings
                    for finding in findings:
                        yield sse("GENESIS_FINDING", {
                            "category":            finding.get("category"),
                            "count":               finding.get("count", 0),
                            "total_monthly_waste": finding.get("total_monthly_waste", 0),
                            "evidence":            finding.get("evidence", ""),
                            "recommendation":      finding.get("recommendation", ""),
                        })

                # ── reporter node events ──────────────────────────────────────
                elif node_name == "reporter":
                    report_path = state.get("report_path", "")
                    findings    = state.get("findings", [])
                    beliefs     = state.get("waste_beliefs", {})

                    total_waste = sum(f.get("total_monthly_waste", 0) for f in findings)

                    yield sse("GENESIS_COMPLETE", {
                        "message":          "Investigation complete",
                        "total_findings":   len(findings),
                        "total_monthly_waste": total_waste,
                        "final_beliefs":    beliefs,
                    })

                    if report_path:
                        yield sse("GENESIS_REPORT_READY", {
                            "report_path":     report_path,
                            "download_url":    f"/api/cost/report/{Path(report_path).name}",
                            "total_monthly_waste": total_waste,
                            "annual_projection": total_waste * 12,
                        })

                await asyncio.sleep(0)  # yield control

        except Exception as e:
            tb = traceback.format_exc()
            yield sse("GENESIS_ERROR", {
                "message": str(e),
                "traceback": tb[-2000:],
            })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


# ── report download ───────────────────────────────────────────────────────────

@app.get("/api/cost/report/{filename}")
async def download_report(filename: str):
    path = Path("reports") / filename
    if not path.exists():
        return {"error": "Report not found"}
    return FileResponse(str(path), media_type="application/pdf",
                        filename=filename)


# ── direct BigQuery debug endpoint ───────────────────────────────────────────

@app.post("/api/cost/debug/bq")
async def debug_bq():
    """Quick connectivity test — bypasses agent loop."""
    try:
        from google.cloud import bigquery
        import os, json

        project = os.environ["GCP_PROJECT_ID"]
        dataset = os.environ.get("BQ_DATASET", "genesis_cost")

        sa_key = os.environ.get("GCP_SA_KEY_JSON", "")
        if sa_key:
            from google.oauth2 import service_account
            creds  = service_account.Credentials.from_service_account_info(json.loads(sa_key))
            client = bigquery.Client(project=project, credentials=creds)
        else:
            client = bigquery.Client(project=project)

        tables = list(client.list_tables(f"{project}.{dataset}"))
        return {
            "status":  "ok",
            "project": project,
            "dataset": dataset,
            "tables":  [t.table_id for t in tables],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── health check ──────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "agent": "genesis-cost"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.cost_server:app", host="0.0.0.0", port=8001, reload=True)