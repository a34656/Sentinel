# Genesis — Python Backend

Autonomous SRE Incident Response Agent. Investigates infrastructure incidents,
writes its own diagnostic scripts, executes them in a secure sandbox, and
produces a formatted post-mortem — without human intervention.

## Stack

| Layer | Tech |
|---|---|
| Orchestration | LangGraph 0.2.28 |
| LLM | Claude Sonnet 4 (Anthropic) |
| Sandbox | E2B Code Interpreter |
| Web Research | Firecrawl |
| Docs / Reporting | Notion |
| Memory | Supabase |
| AWS data | boto3 (Cost Explorer + CloudWatch) |
| API server | FastAPI + SSE streaming |
| PDF generation | ReportLab |

## Setup

```bash
# 1. Copy and fill in your API keys
cp .env.example .env

# 2. Start with Docker (recommended)
docker-compose up --build

# 3. API available at http://localhost:8000
#    Swagger docs at http://localhost:8000/docs
```

### Without Docker

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn api.server:app --reload --port 8000
```

## Test the core loop

```bash
curl -X POST http://localhost:8000/api/incident \
  -H "Content-Type: application/json" \
  -d '{"prompt": "My AWS bill went up 40% overnight. Find the cause and fix it."}'
```

Watch the SSE stream print agent steps in real time.

## File structure

```
genesis_backend/
├── agents/
│   ├── master.py           Master orchestrator — reasons and routes
│   ├── engineer.py         Writes + executes Python in E2B sandbox
│   ├── scout.py            Crawls docs via Firecrawl
│   ├── analyst.py          Pulls AWS Cost Explorer / CloudWatch data
│   ├── scribe.py           Reads runbooks + publishes to Notion
│   ├── report_generator.py Produces PDF post-mortem via ReportLab
│   ├── policy_guard.py     UEBA — blocks destructive actions
│   └── memory_agent.py     Stores + retrieves incidents via Supabase
├── core/
│   ├── config.py           All config + env var loading
│   ├── state.py            AgentState TypedDict
│   └── graph.py            LangGraph wiring
├── api/
│   └── server.py           FastAPI + SSE streaming
├── reports/                Generated PDFs (git-ignored)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## Supabase table

Run this SQL in your Supabase SQL editor before first run:

```sql
create table incident_memory (
  id                uuid primary key,
  created_at        timestamptz default now(),
  incident_id       text,
  incident_prompt   text,
  root_cause        text,
  confidence_score  float,
  fix_applied       boolean,
  fix_blocked       boolean,
  notion_url        text,
  scripts_count     int,
  scripts_json      text
);
```

## Kill switch

```bash
curl -X POST http://localhost:8000/api/incident/{incident_id}/kill
```

## Day-by-day build order

1. **Day 1** — Confirm E2B sandbox works: `engineer.py` executes hello-world Python
2. **Day 2** — Full master → engineer → retry loop on a dirty CSV task
3. **Day 3** — Add analyst (boto3), scout (Firecrawl), policy_guard
4. **Day 4** — Wire to Next.js frontend via SSE stream
5. **Day 5** — Lock, rehearse, record backup video
