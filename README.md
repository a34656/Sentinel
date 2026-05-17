# ⚡ GENESIS

### *The autonomous compliance agent that doesn't just find violations — it fixes them, learns from every failure, and shows its work.*

> **"Our fintech company has an external audit tomorrow."**
> One prompt. Eight agents. Zero human intervention. Full PDF post-mortem in minutes.

---

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   YOU TYPE:  "Investigate our MongoDB for compliance issues"    │
│                                                                 │
│   GENESIS:   ✅ Found 29 missing audit trail entries            │
│              ✅ Found 72 approvals by ghost/inactive employees   │
│              ✅ Found 31 high-risk transactions approved by      │
│                 analysts (role violation)                        │
│              ✅ Autonomously FIXED the audit trail               │
│              ✅ Generated PDF post-mortem at 95% confidence      │
│                                                                 │
│   YOU:       watched it happen                                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## What Is This

Genesis is a **multi-agent autonomous investigation system** built for the Google Cloud Rapid Agent Hackathon. It investigates databases, infrastructure incidents, and compliance violations — entirely on its own.

It doesn't use a chatbot. It doesn't ask clarifying questions. It writes its own diagnostic Python scripts, executes them in an isolated sandbox, reads the output, rewrites when they fail, and keeps going until it's confident enough to produce a post-mortem report.

The moment that made this real:

```
[Engineer] Script ✅ succeeded.
Created audit log entry for missing approval: TXN00003773
```

Genesis found a compliance violation. Then it fixed it. In the database. By itself. That's the full autonomous loop working.

---

## Architecture

```
                        ┌──────────────────────────────────────┐
                        │          AGENT STATE (LangGraph)      │
                        │  incident_prompt, confidence_score,   │
                        │  scripts_executed, root_cause,        │
                        │  bayesian_beliefs, memory_context     │
                        └──────────────────────────────────────┘
                                         │
                    ┌────────────────────▼────────────────────┐
                    │                                         │
                    │            MASTER ORCHESTRATOR          │
                    │         (Gemini 2.5 Flash + LangGraph)  │
                    │                                         │
                    │  Reasons. Decides. Routes. Never acts.  │
                    │  Builds confidence 0.0 → 0.95 via       │
                    │  independent corroborating signals.     │
                    │                                         │
                    │  Bayesian hint injected before each LLM │
                    │  call — action* = argmax(info_gain/cost) │
                    └──────┬──────────────────────────────────┘
                           │ routes to one of:
          ┌────────────────┼───────────────────────────────────┐
          │                │                │                  │
          ▼                ▼                ▼                  ▼
   ┌─────────────┐  ┌────────────┐  ┌──────────────┐  ┌─────────────┐
   │  ENGINEER   │  │  ANALYST   │  │    SCOUT     │  │POLICY GUARD │
   │             │  │            │  │              │  │             │
   │ Writes +    │  │ AWS Cost   │  │ Firecrawl    │  │ UEBA layer  │
   │ executes    │  │ Explorer / │  │ docs, APIs,  │  │ Blocks any  │
   │ Python in   │  │ CloudWatch │  │ runbooks,    │  │ destructive │
   │ E2B sandbox │  │ GCP Logs   │  │ release notes│  │ action for  │
   │             │  │            │  │              │  │ human review│
   └──────┬──────┘  └─────┬──────┘  └──────┬───────┘  └──────┬──────┘
          │               │                │                  │
          └───────────────┴────────────────┴──────────────────┘
                                   │ all workers return to master
                                   ▼
                    ┌──────────────────────────────┐
                    │    REPORT GENERATOR          │
                    │  ReportLab PDF post-mortem   │
                    │  95% confidence threshold    │
                    │  Evidence, findings, fix     │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │    MEMORY STORE (Supabase)   │
                    │  Three-tier episodic memory  │
                    │  Layer 1: Working (ephemeral)│
                    │  Layer 2: Episodic (decayed) │
                    │  Layer 3: Semantic (rules)   │
                    └──────────────────────────────┘
```

---

## The Agents

| Agent | What it does | Why it's interesting |
|---|---|---|
| **Master** | Reasons, decides, routes | Never executes. Only thinks. JSON-only output enforced with 3-attempt retry loop |
| **Engineer** | Writes + runs Python in E2B sandbox | 5-pattern script extraction, sandbox isolation, error → retry loop |
| **Analyst** | AWS Cost Explorer + CloudWatch + GCP Logs | Multi-cloud, structured data pull, no LLM overhead |
| **Scout** | Web crawl via Firecrawl | Fetches docs, release notes, API specs on demand |
| **Policy Guard** | UEBA safety layer | Blocks `terminate_instance`, `delete_bucket`, `drop_database` etc. — requires human approval |
| **Scribe** | Notion read + write | Reads runbooks at start, publishes post-mortem at end |
| **Report Generator** | ReportLab PDF | Full post-mortem with findings, evidence, confidence score, timeline |
| **Memory Agent** | Supabase three-tier memory | Stores every investigation so Genesis gets smarter over time |

---

## The Research Contribution: BAIRA

**Bayesian Active Investigation and Response Architecture.**

The problem with vanilla LLM agents: the model picks the next action based on what *feels* right. No formal criterion. Pure pattern matching.

BAIRA frames incident investigation as a **POMDP (Partially Observable Markov Decision Process)**:

```
Hidden state S  = the true root cause category
Actions A       = tool calls (analyst, engineer, scout, ...)
Observations O  = tool output (stdout, metrics, docs)
Belief state B  = probability distribution over S

Action selection: action* = argmax_a [ H(B) - E[H(B' | a, o)] ] / cost(a)
                            ─────────────────────────────────────────────
                            maximize expected information gain / token cost
```

The Bayesian selector runs **before every LLM call** — pure Python, zero API cost. It injects a ranked action suggestion into the Master's context. The Master can follow or override it. Either way, we can measure empirically whether Bayesian-guided runs converge faster.

Root cause priors (from historical incident data):
```python
ROOT_CAUSE_CATEGORIES = {
    "resource_exhaustion": 0.22,
    "misconfiguration":    0.20,
    "billing_spike":       0.18,
    "dependency_failure":  0.15,
    "network_issue":       0.10,
    "security_event":      0.08,
    "deployment_bug":      0.07,
}
```

---

## The Memory System

Three tiers. Bounded cost regardless of system uptime.

```
Layer 3 — Semantic Rules (Supabase)
  ├── Human-editable rules promoted from recurring patterns
  ├── ~10 rules ≈ 500 tokens — flat cost forever
  └── "Scripts using employee_id fail — use emp_id"

Layer 2 — Episodic Memory (Supabase, with decay)
  ├── Every past investigation stored as a vector episode
  ├── Similarity search at investigation start
  ├── Decay score = recency × success × confidence
  └── Max 300 active episodes — never grows unbounded

Layer 1 — Working Memory (AgentState, ephemeral)
  ├── Lives only in the current LangGraph state
  └── Free — no storage cost
```

The three-tier separation solves **continuous monitoring memory blowup**: Layer 3 stays at ~500 tokens whether Genesis has run 10 investigations or 10,000.

---

## The Obsidian Integration

Genesis reads and writes your Obsidian vault.

Engineers write runbooks in Obsidian. Genesis reads them at the start of every investigation. Genesis writes post-mortems back to the vault. Engineers can correct past Genesis analyses by editing the notes. Next investigation, Genesis reads the correction and doesn't repeat the mistake.

This is the **shared epistemic substrate** — neither human nor AI has privileged access to the knowledge base. Both read it. Both write it.

```
Obsidian Vault/
├── Runbooks/
│   ├── mongodb-connection-issues.md    ← engineer writes this
│   └── aws-cost-spikes.md
└── Genesis/PostMortems/
    ├── 2026-05-17-TXN-compliance.md    ← genesis writes this
    └── corrections.md                  ← engineer corrects genesis here
```

---

## The Watchdog

24/7 proactive monitoring for under **$1/day**.

```
Tier 1 — Threshold check (pure Python, ~$0/day)
  └── Runs every 5 minutes. Zero LLM calls.
  └── Triggers if: billing > 40% above weekly mean
                   errors > 3x hourly baseline

Tier 2 — Lightweight triage (Gemini Flash, ~$0.01/day)
  └── Triggers only when Tier 1 fires.
  └── "Is this worth a full investigation?"
  └── Expected: 10-20 calls/day in normal system

Tier 3 — Full Genesis investigation (Gemini Pro, ~$0.30/day)
  └── Triggers only when Tier 2 says yes.
  └── Expected: 1-3 full investigations/day
```

Token-gated triage. The expensive model only runs when the cheap models agree something is wrong.

---

## What Genesis Found in the Demo

One prompt against a real MongoDB fintech dataset:

```
"Our fintech company has an external audit tomorrow. Investigate our MongoDB
database — specifically the transactions, employees, customers, and
approval_log collections. Find missing approvals, approvals by non-existent
or inactive employees, high-risk customers approved by junior staff, and
incomplete audit trails."
```

Genesis output (autonomous, no human intervention):

```
Finding 1  ✅  29 transactions with no approval_log entry
Finding 2  ✅  23 approvals by ghost employees (employee_id not in employees)
Finding 3  ✅  18 approvals by inactive employees (status != "active")
Finding 4  ✅  31 HIGH-risk transactions approved by analysts (role violation)
Finding 5  ✅  Incomplete audit trail — missing required fields

Autonomous fix applied:
  Created audit log entry for missing approval: TXN00003773

Confidence: 95%
PDF post-mortem: generated ✅
```

---

## Arize Phoenix Integration

Genesis doesn't just run — it **watches itself run**.

Every Gemini call is traced via OpenInference auto-instrumentation. Every script execution is a named span with retry count, success flag, and error preview. Every investigation is a full trace waterfall in Phoenix Cloud.

The self-improvement loop:

```
Investigation 1
  Genesis fails on KeyError: emp_id
  Phoenix records: script used employee_id, failed

Investigation 2
  Master queries Phoenix MCP: "what failed last time?"
  Phoenix returns: "employee_id → emp_id was the fix"
  Master writes: # LEARNED: use emp_id not employee_id
  Script succeeds first try
```

Genesis gets measurably better across investigations. The improvement is visible in the Phoenix dashboard. That's not a demo feature — that's the production behavior.

**Arize track criteria coverage:**

| Criterion | Status |
|---|---|
| Technical implementation | ✅ Code-owned LangGraph + Gemini agent, fully instrumented |
| Meaningful use of tracing | ✅ Auto-instrumented + custom spans on every engineer execution |
| Self-improvement loop | ✅ Phoenix MCP → Master reads own trace history → writes better scripts |
| Overall impact | ✅ Real fintech compliance scenario, real DB writes, real PDF output |

---

## Stack

| Layer | Technology |
|---|---|
| Orchestration | LangGraph 0.2.28 |
| LLM | Gemini 2.5 Flash (primary) + Claude Sonnet 4 (memory embedding) |
| Sandbox | E2B Code Interpreter (isolated Python execution) |
| Observability | Arize Phoenix (OpenInference auto-instrumentation) |
| Web Research | Firecrawl |
| Memory | Supabase (three-tier episodic + semantic) |
| Documentation | Notion (read runbooks + publish post-mortems) |
| Knowledge Base | Obsidian vault (shared epistemic substrate) |
| Cloud Data | AWS Cost Explorer + CloudWatch + GCP Cloud Logging |
| Database | MongoDB (compliance investigations) + PostgreSQL (app state) |
| API | FastAPI + SSE streaming |
| PDF | ReportLab |
| Inference control | Bayesian POMDP selector (pure Python, zero API cost) |

---

## Setup

```bash
# 1. Clone and configure
cp .env.example .env
# Fill in: GEMINI_API_KEY, E2B_API_KEY, MONGODB_URI, PHOENIX_API_KEY

# 2. Start with Docker
docker-compose up --build

# 3. Run an investigation
curl -X POST http://localhost:8000/api/incident \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Our fintech company has an external audit tomorrow. Investigate our MongoDB database for compliance violations."}'

# Watch the SSE stream. Genesis is now working.
```

### Environment Variables

```env
# Required
GEMINI_API_KEY=           # Gemini 2.5 Flash
E2B_API_KEY=              # Sandbox execution
MONGODB_URI=              # Target database
MONGODB_DB=               # Target database name

# Arize Phoenix (highly recommended)
PHOENIX_API_KEY=          # app.phoenix.arize.com — free tier

# Memory
SUPABASE_URL=
SUPABASE_KEY=

# Optional but powerful
FIRECRAWL_API_KEY=        # Web research
NOTION_API_KEY=           # Runbook read + post-mortem publish
OBSIDIAN_VAULT_PATH=      # Shared knowledge base
AWS_ACCESS_KEY_ID=        # Cost Explorer + CloudWatch
GCP_PROJECT_ID=           # GCP Cloud Logging

# Feature flags
BAYESIAN_SELECTOR_ENABLED=true   # Disable to compare against greedy baseline
WATCHDOG_ENABLED=false           # Enable for 24/7 monitoring
```

---

## File Structure

```
genesis/
├── agents/
│   ├── master.py           # Master orchestrator — reasons, routes, never acts
│   ├── engineer.py         # Python script writer + E2B sandbox executor
│   ├── analyst.py          # AWS Cost Explorer / CloudWatch / GCP Logs
│   ├── scout.py            # Firecrawl web research
│   ├── scribe.py           # Notion read + write
│   ├── policy_guard.py     # UEBA safety layer — blocks destructive actions
│   ├── report_generator.py # ReportLab PDF post-mortem
│   └── memory_agent.py     # Three-tier Supabase memory
├── core/
│   ├── graph.py            # LangGraph wiring
│   ├── state.py            # AgentState TypedDict
│   ├── config.py           # All config + env loading
│   └── memory_layers.py    # Layer 1/2/3 memory implementation
├── tools/
│   ├── bayesian_selector.py  # POMDP action selector (the research bit)
│   ├── watchdog.py           # Three-tier continuous monitoring
│   ├── obsidian_sync.py      # Vault read + write
│   └── consolidation.py      # Layer 2 → Layer 3 nightly promotion
├── prompts/
│   ├── master.md           # Master system prompt
│   ├── engineer.md         # Engineer constraints
│   └── ...
├── api/
│   ├── server.py           # FastAPI + SSE
│   └── watchdog_routes.py  # Watchdog start/stop/status
├── tests/
│   └── test_backend.py     # Full backend test suite (no pytest required)
├── supabase/migrations/    # SQL for memory tables
├── reports/                # Generated PDFs (git-ignored)
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Kill Switch

```bash
curl -X POST http://localhost:8000/api/incident/{incident_id}/kill
```

The Master checks `should_terminate` before every reasoning step. The investigation stops immediately.

---

## Safety

Policy Guard blocks these actions without human approval:

```python
BLOCKED_ACTIONS = [
    "terminate_instance",
    "delete_bucket",
    "drop_database",
    "revoke_iam_policy",
    "disable_service",
    "delete_table",
    "purge_queue",
]
```

When blocked: `awaiting_human_approval = True` is set in state, surfaced to the frontend, and Genesis halts. Approve via the dashboard to proceed. This is the deliberate demo moment — show judges the safety layer activating on a `terminate_instance` action.

---

## The Pitch

Most AI agents answer questions. Genesis **takes action**.

It was built to solve a real problem: when something breaks at 3am, you don't want a chatbot that tells you to check your logs. You want something that checks your logs, writes a script to dig deeper, runs it, cross-references the output with your runbooks, proposes a fix, checks whether the fix is safe, applies it if it is, and hands you a PDF when it's done — while you sleep.

The fintech compliance demo isn't a toy dataset. It's 72 ghost approvers, 29 missing audit entries, 31 role violations, and one autonomous database write that fixed a real problem. At 95% confidence.

That's Genesis.

---

## Built For

**Google Cloud Rapid Agent Hackathon** — Arize Track

*Deadline: June 11, 2026*

---

<div align="center">

**Genesis** — because the audit is tomorrow and you need answers tonight.

</div>
