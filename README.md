<div align="center">

```
 ██████╗ ███████╗███╗   ██╗███████╗███████╗██╗███████╗
██╔════╝ ██╔════╝████╗  ██║██╔════╝██╔════╝██║██╔════╝
██║  ███╗█████╗  ██╔██╗ ██║█████╗  ███████╗██║███████╗
██║   ██║██╔══╝  ██║╚██╗██║██╔══╝  ╚════██║██║╚════██║
╚██████╔╝███████╗██║ ╚████║███████╗███████║██║███████║
 ╚═════╝ ╚══════╝╚═╝  ╚═══╝╚══════╝╚══════╝╚═╝╚══════╝
```

**Autonomous Financial Intelligence Agent**

*One prompt. Eight agents. Zero human intervention.*
*Finds violations. Fixes them. Learns from every run.*

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Gemini](https://img.shields.io/badge/Gemini-2.5_Flash-4285F4?style=flat-square&logo=google&logoColor=white)](https://deepmind.google/gemini)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2.28-1C3C3C?style=flat-square)](https://langchain.com/langgraph)
[![Arize Phoenix](https://img.shields.io/badge/Arize-Phoenix-7C3AED?style=flat-square)](https://phoenix.arize.com)
[![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-47A248?style=flat-square&logo=mongodb&logoColor=white)](https://mongodb.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)

---

*Built for the **Google Cloud Rapid Agent Hackathon** — Arize Track*

</div>

---

## The Idea

Every other AI agent answers questions. **Genesis investigates.**

You type one sentence. Genesis deploys eight specialist agents — writing its own Python scripts, executing them in an isolated sandbox, cross-referencing databases, learning from every failure via Arize Phoenix traces — and hands you a signed PDF post-mortem when it's done.

The moment that made this real:

```
[Engineer] Script ✅ succeeded.
Created audit log entry for missing approval: TXN00003773
```

Genesis found a compliance violation. Then it **fixed it**. In the database. By itself. That's not a demo feature — that's the production behaviour.

---

## What Genesis Can Investigate

### 🔍 Playbook A — Fintech Compliance Audit
```
"Our fintech company has an external audit tomorrow.
 Investigate our MongoDB database for compliance violations."
```
Genesis finds all 5 violation categories autonomously:

| Finding | What Genesis Looks For | Result |
|---|---|---|
| F1 | Transactions with no approval entry | 47 found |
| F2 | Approvals by ghost employee IDs | 23 found |
| F3 | Approvals by deactivated employees | 18 found |
| F4 | HIGH-risk customers approved by analysts | 34 found |
| F5 | Incomplete audit trail entries | 29 found |

Then it **fixes** what it can — autonomously creating missing audit log entries and writing compliance flags back to the database.

---

### 🕸 Playbook B — AML Network Graph Investigation
```
"Investigate our IBM AML transaction dataset for money laundering
 networks. Find smurfing, fan-out patterns, and circular money flows."
```
Genesis reads 50,000 IBM AML transactions directly from CSV with pandas, builds a directed transaction graph using networkx, and detects four money laundering typologies:

- **Fan-Out (Smurfing)** — one account distributing to many recipients
- **Fan-In (Aggregation)** — many accounts funnelling into one
- **Cycles** — circular money flows (A→B→C→A)
- **Structuring** — repeated transactions just below the $10,000 reporting threshold

Outputs a scored suspect list and structured graph JSON for the frontend to render as a live D3 network graph.

---

### 💼 Playbook C — Personalized Wealth Management
```
"Analyse our client portfolio data for risk concentrations,
 generate personalized recommendations, and flag anomalous trading."
```
Using the same IBM dataset reframed as portfolio data:

- **Client segmentation** — Ultra-HNW, HNW, Affluent, Retail
- **Herfindahl diversification scoring** — per-client concentration index
- **Anomalous trading detection** — velocity anomalies, wash trading, rapid currency shifts
- **Personalized recommendations** — rebalance suggestions, compliance flags, wealth health scores per client

---

## How It Works

```
You type a prompt
        │
        ▼
┌───────────────────────────────────────────────────────┐
│                  MASTER ORCHESTRATOR                  │
│            Gemini 2.5 Flash + LangGraph               │
│                                                       │
│  Reads memory → matches playbook → reasons → routes  │
│  Never executes. Only thinks.                         │
│  Bayesian POMDP selector picks lowest-cost action.   │
└──────┬────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────┐
│                  APPROVAL GATE                       │
│                                                      │
│  Master proposes a script.                           │
│  Shows you: what it will do + plain English reason.  │
│  You approve → Engineer executes.                    │
│  You reject  → Master tries a different approach.    │
│  Auto-approves after 60s so demo never stalls.       │
└──────┬───────────────────────────────────────────────┘
       │  approved
       ▼
┌──────────────────────────────────────────────────────┐
│                    ENGINEER                          │
│                                                      │
│  Writes Python. Runs it in E2B sandbox.              │
│  Reads stdout. Retries on failure (max 3x).          │
│  Intercepts GENESIS_GRAPH_DATA: marker →             │
│  emits graph_data SSE event to frontend.             │
└──────┬───────────────────────────────────────────────┘
       │ result
       ▼
    MASTER reasons again
       │
       ├──→ SCOUT        (Firecrawl web research)
       ├──→ ANALYST      (AWS Cost Explorer / GCP Logs)
       ├──→ POLICY GUARD (blocks destructive actions)
       ├──→ SCRIBE       (reads Notion runbooks, writes post-mortems)
       ├──→ MEMORY AGENT (three-tier Supabase memory)
       └──→ REPORT GENERATOR → PDF post-mortem
```

---

## The Approval Gate

Before Genesis runs any script, it pauses and tells you exactly what it's about to do:

```
⏸  GENESIS WANTS TO RUN

  "Query the approval_log collection to find transactions
   with no matching approval entry"

  Reasoning: I have 47 transactions flagged as missing approvals,
  need to verify exact count before reporting.

  Script: 34 lines of Python

  [APPROVE ✓]   [REJECT ✗]   (auto-approves in 60s)
```

Approve → it runs and continues autonomously.
Reject → Master re-reasons and tries a different, safer approach.

This is the **Antigravity pattern** — the agent asks permission before touching anything, then operates fully autonomously once cleared.

---

## The Research: BAIRA

**Bayesian Active Investigation and Response Architecture.**

Standard LLM agents pick the next action by vibes. BAIRA frames investigation as a POMDP:

```
Hidden state  S = true root cause category
Actions       A = tool calls (engineer, analyst, scout…)
Observations  O = tool output (stdout, metrics, docs)
Belief state  B = probability distribution over S

Optimal action: a* = argmax_a [ H(B) - E[H(B'|a,o)] ] / cost(a)
                     ────────────────────────────────────────────
                     maximize information gain per token spent
```

Root cause priors from historical incident data:
```python
ROOT_CAUSE_PRIORS = {
    "resource_exhaustion": 0.22,
    "misconfiguration":    0.20,
    "billing_spike":       0.18,
    "dependency_failure":  0.15,
    "network_issue":       0.10,
    "security_event":      0.08,
    "deployment_bug":      0.07,
}
```

The selector runs **before every LLM call** — pure Python, zero API cost. It injects a ranked action suggestion into Master's context. You can disable it with `BAYESIAN_SELECTOR_ENABLED=false` and compare convergence speed against the greedy baseline.

---

## The Memory System

Three tiers. Bounded cost no matter how long Genesis runs.

```
Layer 3 — Semantic Rules          ~500 tokens, flat cost forever
  Human-editable rules promoted from recurring patterns.
  "Scripts using employee_id fail — use emp_id"
  "MongoDB aggregations over 16MB hit Atlas memory limit"

Layer 2 — Episodic Memory         max 300 active episodes
  Every past investigation as a vector in Supabase.
  Similarity search at investigation start.
  Decay score = recency × success × confidence.

Layer 1 — Working Memory          free, ephemeral
  Lives only in LangGraph AgentState for current run.
```

---

## The Self-Improvement Loop (Arize Phoenix)

Every Gemini call is traced. Every script execution is a named span. Every failure is a structured event.

```
Investigation 1
  Genesis fails: KeyError on field name
  Phoenix records: script used employee_id, failed

Investigation 2
  Master queries Phoenix MCP: "what failed last run?"
  Phoenix returns: "employee_id → emp_id was the fix"
  Master writes: # LEARNED: use emp_id not employee_id
  Script succeeds first try
```

Genesis gets measurably better across investigations. The improvement is visible in the Phoenix dashboard at `app.phoenix.arize.com`.

**Arize track criteria:**

| Criterion | Status |
|---|---|
| Technical implementation | ✅ Code-owned LangGraph + Gemini, fully instrumented |
| Meaningful use of tracing | ✅ Auto-instrumented + custom spans on every engineer execution |
| Self-improvement loop | ✅ Phoenix MCP → Master reads own traces → writes better scripts |
| Overall impact | ✅ Real fintech scenario, real DB writes, real PDF output |

---

## The Watchdog

Proactive 24/7 monitoring for under **$1/day**.

```
Tier 1 — Threshold check     ~$0/day
  Pure Python. Runs every 5 minutes. Zero LLM calls.
  Triggers if billing > 40% above weekly mean
           or errors > 3× hourly baseline.

Tier 2 — Lightweight triage  ~$0.01/day
  Gemini Flash. Only when Tier 1 fires.
  "Is this worth a full investigation?"

Tier 3 — Full investigation  ~$0.30/day
  Full Genesis pipeline. Only when Tier 2 says yes.
```

Token-gated triage. The expensive model only runs when the cheap models agree something is wrong.

---

## Agent Roster

| Agent | Role | Superpower |
|---|---|---|
| **Master** | Orchestrator | Reasons, routes, never executes. JSON-only output with 3-attempt retry loop |
| **Engineer** | Script executor | Writes + runs Python in E2B sandbox. Intercepts graph data markers |
| **Analyst** | Data puller | AWS Cost Explorer + CloudWatch + GCP Cloud Logging |
| **Scout** | Web researcher | Firecrawl — fetches docs, runbooks, API specs on demand |
| **Policy Guard** | Safety layer | Blocks `drop_database`, `terminate_instance`, `delete_bucket` etc. — requires human approval |
| **Scribe** | Knowledge I/O | Reads Notion runbooks at start, publishes post-mortems at end |
| **Report Generator** | PDF writer | ReportLab post-mortem with findings, evidence, confidence, timeline |
| **Memory Agent** | Long-term memory | Three-tier Supabase store — Genesis remembers across investigations |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Orchestration | LangGraph 0.2.28 |
| LLM | Gemini 2.5 Flash Lite |
| Deployment | Google Cloud Agent Engine (Vertex AI) |
| Sandbox | E2B Code Interpreter |
| Observability | Arize Phoenix (OpenInference) |
| Web research | Firecrawl |
| Memory | Supabase (pgvector) |
| Documentation | Notion |
| Knowledge base | Obsidian vault |
| Cloud metrics | AWS Cost Explorer + CloudWatch + GCP Cloud Logging |
| Database | MongoDB Atlas + PostgreSQL |
| API | FastAPI + SSE streaming |
| Frontend | Next.js 14 + TypeScript + Tailwind + D3 |
| PDF | ReportLab |
| Inference control | Bayesian POMDP selector (pure Python) |

---

## Project Structure

```
genesis/
├── agents/
│   ├── master.py            # Orchestrator — reasons and routes only
│   ├── engineer.py          # Script writer + E2B executor
│   ├── analyst.py           # AWS + GCP data puller
│   ├── scout.py             # Firecrawl web research
│   ├── scribe.py            # Notion read + write
│   ├── policy_guard.py      # UEBA safety layer
│   ├── report_generator.py  # ReportLab PDF
│   ├── memory_agent.py      # Three-tier memory
│   └── approval_gate.py     # Pre-execution pause + approval
├── core/
│   ├── graph.py             # LangGraph wiring
│   ├── state.py             # AgentState TypedDict
│   ├── config.py            # Env + config loading
│   └── memory_layers.py     # Layer 1/2/3 implementation
├── tools/
│   ├── bayesian_selector.py # POMDP action selector
│   ├── watchdog.py          # Three-tier monitoring
│   ├── obsidian_sync.py     # Vault read + write
│   └── consolidation.py    # Layer 2 → 3 promotion
├── investigations/
│   ├── aml_pandas_investigation.py   # Playbook B script
│   └── cross_border_ghost_tracker.py # Playbook C script
├── prompts/
│   ├── master.md            # Master system prompt + all playbooks
│   └── engineer.md          # Engineer constraints
├── scripts/
│   └── load_aml_data.py     # One-time IBM CSV → MongoDB loader
├── api/
│   ├── server.py            # FastAPI + SSE + graph data streaming
│   ├── planner_routes.py    # Approval gate endpoints
│   └── watchdog_routes.py   # Watchdog start/stop/status
├── data/
│   └── HI-Small_Trans.csv   # IBM AML dataset (not committed)
├── reports/                 # Generated PDFs (git-ignored)
├── supabase/migrations/     # Memory table SQL
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Setup

### Prerequisites
- Python 3.11+
- Node.js 18+
- Docker
- A Google Cloud project with billing enabled

### 1. Clone and configure
```bash
git clone https://github.com/your-username/genesis
cd genesis
cp .env.example .env
```

### 2. Fill in `.env`
```env
# Required
GEMINI_API_KEY=              # Gemini 2.5 Flash
E2B_API_KEY=                 # sandbox.e2b.dev — free tier available
MONGODB_URI=                 # MongoDB Atlas connection string
MONGODB_DB=genesis_compliance

# IBM AML dataset
AML_CSV_PATH=/absolute/path/to/HI-Small_Trans.csv
AML_SAMPLE_SIZE=50000

# Arize Phoenix (get free key at app.phoenix.arize.com)
PHOENIX_API_KEY=
PHOENIX_COLLECTOR_ENDPOINT=https://app.phoenix.arize.com/v1/traces

# Memory
SUPABASE_URL=
SUPABASE_KEY=

# Optional
FIRECRAWL_API_KEY=           # Web research
NOTION_API_KEY=              # Runbook read + post-mortem publish
OBSIDIAN_VAULT_PATH=         # Shared knowledge base
AWS_ACCESS_KEY_ID=           # Cost Explorer + CloudWatch
GCP_PROJECT_ID=              # GCP Cloud Logging

# Feature flags
BAYESIAN_SELECTOR_ENABLED=true
WATCHDOG_ENABLED=false
```

### 3. Start backend
```bash
pip install -r requirements.txt
python -m uvicorn api.server:app --reload --port 8000
```

### 4. Start frontend
```bash
cd frontend
npm install
npm run dev
# Open http://localhost:3000
```

### 5. (Optional) Load IBM AML data into MongoDB
```bash
python scripts/load_aml_data.py \
  --csv /path/to/HI-Small_Trans.csv \
  --sample 50000
```

### 6. (Optional) Deploy to GCP Agent Engine
```bash
pip install google-cloud-aiplatform[agent_engines,langchain]
python deploy.py
```

---

## Try It

### Compliance Audit
```bash
curl -X POST http://localhost:8000/api/incident \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Our fintech company has an external audit tomorrow. Investigate our MongoDB database for missing approvals, ghost employees, and role violations."}'
```

### AML Network Investigation
```bash
curl -X POST http://localhost:8000/api/incident \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Investigate our IBM AML transaction dataset for money laundering networks. Find smurfing, fan-out patterns, and circular money flows."}'
```

### Wealth Management Analysis
```bash
curl -X POST http://localhost:8000/api/incident \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Analyse our client portfolio data for risk concentrations, generate personalized wealth management recommendations, and flag anomalous trading patterns."}'
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/incident` | Start investigation (SSE stream) |
| `POST` | `/api/incident/{id}/approve-script` | Approve pending script |
| `POST` | `/api/incident/{id}/reject-script` | Reject — Master re-reasons |
| `POST` | `/api/incident/{id}/approve` | PolicyGuard human approval |
| `POST` | `/api/incident/{id}/kill` | Kill switch |
| `GET`  | `/api/incident/{id}/pending-script` | Poll pending script (reconnect) |
| `GET`  | `/api/incidents` | Investigation history |
| `GET`  | `/health` | Health check |

### SSE Event Types

| Event | When | Payload |
|---|---|---|
| `init` | Investigation starts | `incident_id` |
| `step` | Every agent step | `node, step_log, confidence_score, root_cause` |
| `graph_data` | AML/wealth script completes | `nodes, edges, suspects, summary` |
| `awaiting_script_approval` | Approval gate fires | `script, what_it_does, reasoning` |
| `log` | Every Loguru log line | `level, message, module` |
| `complete` | Investigation ends | `incident_id, root_cause` |
| `error` | Unhandled exception | `message` |
| `killed` | Kill switch activated | `incident_id` |

---

## Safety

Policy Guard blocks these without human approval:

```python
BLOCKED_ACTIONS = [
    "terminate_instance", "delete_bucket",   "drop_database",
    "revoke_iam_policy",  "disable_service", "delete_table",
    "purge_queue",        "destroy",         "wipe",
]
```

When blocked: `awaiting_human_approval = True` is set in state and streamed to the frontend. Genesis halts. Approve or reject via the dashboard. This is a **deliberate demo moment** — show judges the safety layer activating.

---

## Hackathon

Built for the **Google Cloud Rapid Agent Hackathon — Arize Track**

**Why Genesis wins:**

| What judges look for | What Genesis has |
|---|---|
| Goes beyond chatbot | Autonomous DB writes, PDF generation, sandbox execution |
| Multi-step planning | 8-agent LangGraph pipeline with Bayesian action selection |
| Partner MCP integration | Arize Phoenix MCP — agent queries its own traces |
| Self-improvement loop | Master reads Phoenix trace history before each investigation |
| Real-world impact | Three investigation modes: compliance, AML, wealth management |
| GCP Agent Builder | Deployed on Vertex AI Agent Engine |

---

## The Pitch

> *"Genesis doesn't just find compliance violations — it fixes them, learns from every failure via Arize Phoenix traces, and arrives at each audit better than the last. Three investigation modes. One prompt each. Full PDF post-mortem at 95% confidence. And it asked permission before touching anything."*

---

<div align="center">

**Genesis** — because the audit is tomorrow and you need answers tonight.

MIT License · Built with Gemini · Traced by Arize · Deployed on GCP

</div>