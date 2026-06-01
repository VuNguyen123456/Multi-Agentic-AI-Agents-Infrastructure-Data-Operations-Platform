# Multi-Agent Infrastructure Recovery System

An autonomous AIOps platform that detects, diagnoses, plans, and recovers from data pipeline failures using six specialized AI agents orchestrated by LangGraph — with human oversight for high-risk actions, real Azure cloud telemetry ingestion, and full audit persistence.

Built from scratch as a learning and portfolio project. Every architectural decision is intentional and documented below.

---

## What It Does

When a data pipeline fails, this system autonomously:

1. **Detects** the failure and classifies its type across 8 failure categories
2. **Diagnoses** the root cause by reasoning over logs and metrics
3. **Plans** a concrete, ordered recovery procedure with risk estimation
4. **Validates** the plan — auto-approves low-risk actions, escalates high-risk to a human
5. **Executes** the recovery steps if approved
6. **Logs** a complete structured incident report to PostgreSQL

No human intervention required for low-risk recoveries. High-risk actions (schema changes, service restarts, data deletion) pause the entire workflow and wait for explicit human approval before anything executes.

**Design principle: safety over speed — always escalate rather than guess on destructive actions.**

---

## Architecture

Six specialized AI agents, each with a single responsibility, orchestrated by LangGraph:

```
[Data Source]
  mock: failure_sim.py (8 scenarios)
  real: Azure Application Insights → KQL REST API
        ↓
[Monitoring Agent]    detects failure, classifies type
        ↓
[Analysis Agent]      finds root cause from logs + metrics
        ↓
[Planning Agent]      generates ordered recovery steps + risk estimate
        ↓
[Security Agent]      validates risk, makes final approval decision
        ↓
   low risk ──────────────────────────────────────→ [Execution Agent]
   high risk → graph PAUSES → human approves/rejects via API
               └─ approved ────────────────────────→ [Execution Agent]
               └─ rejected ──────────────────────────────────────────┐
                                                                      ↓
                                                             [Audit Agent]
                                                                      ↓
                                                    PostgreSQL incident saved
                                                    Azure Function triggered (on approve)
```

**Key design decisions:**
- Agents never call each other directly — they communicate exclusively through a shared `AgentState` TypedDict
- LangGraph merges partial state updates after each node
- Each agent is one focused Claude API call with a scoped system prompt
- The Security Agent has a Python-level hard gate — `approved` is forced `False` when `risk_level == "high"`, regardless of LLM output

---

## Tech Stack

| Layer | Technology | Role |
|---|---|---|
| Agent Framework | LangGraph 1.2.1 | Multi-agent graph, conditional routing, interrupts |
| LLM | Claude claude-opus-4-5 (Anthropic) | All 6 agents — structured JSON output |
| State Persistence | Redis Stack (langgraph-checkpoint-redis) | Graph pause/resume across human approval |
| Backend API | FastAPI 0.136.3 + Uvicorn | Control plane, approval endpoints |
| Database | PostgreSQL 15 | Persistent incident audit log |
| Observability | Prometheus + Grafana + postgres_exporter | Metrics, dashboards, DB analytics |
| Azure — Ingest | Application Insights + KQL REST API | Real cloud telemetry → agent pipeline |
| Azure — Execute | Azure Functions (Linux, Python 3.11) | Post-approval remediation hook |
| Containers | Docker + Docker Compose | Local infrastructure stack |
| Orchestration | Kubernetes (Docker Desktop) | API deployment with health probes |
| Language | Python 3.12 | Runtime |

---

## Project Structure

```
project/
├── agents/
│   ├── monitoring_agent.py     # failure detection + classification (8 types)
│   ├── analysis_agent.py       # root cause analysis from logs + metrics
│   ├── planning_agent.py       # recovery plan generation + risk estimation
│   ├── security_agent.py       # risk validation + approval gate
│   ├── execution_agent.py      # recovery execution + result tracking
│   └── audit_agent.py          # incident report generation + DB write
├── orchestrator/
│   └── graph.py                # LangGraph StateGraph — all nodes, edges, routers, interrupt
├── simulator/
│   └── failure_sim.py          # 8 simulated failure scenarios (mock data source)
├── azure/
│   ├── ingest.py               # KQL query → App Insights → AgentState
│   ├── execute.py              # POST to Azure Function after human approval
│   ├── emit_failures.py        # seed App Insights with test failure events
│   └── function_app/           # Azure Function source (deploy to infra-recovery-executor)
│       ├── function_app.py
│       ├── requirements.txt
│       └── host.json
├── api/
│   └── main.py                 # FastAPI app — all HTTP endpoints
├── db/
│   ├── schema.sql              # PostgreSQL schema + indexes + view
│   └── database.py             # save_incident, get_recent_incidents, get_stats
├── observability/
│   ├── metrics.py              # Prometheus counters, gauges, histograms
│   ├── graph_tracking.py       # tracked_invoke — per-node step + duration metrics
│   └── summary.py              # /metrics/summary — live bars for dashboard
├── k8s/
│   ├── deployment.yaml         # 1-replica API pod, readiness/liveness probes
│   ├── service.yaml            # LoadBalancer on port 8000
│   ├── configmap.yaml          # non-secret env vars (Postgres host, Redis URL)
│   └── secret.yaml             # API keys + DB password
├── prometheus/
│   └── prometheus.yml          # scrape config (API + postgres_exporter)
├── grafana/
│   └── provisioning/           # auto-load datasources + dashboards
├── state.py                    # AgentState TypedDict — single schema for all agents
├── main.py                     # CLI entry point (stateless, no pause/resume)
├── dashboard.html              # Operator UI — dark ops dashboard
├── Dockerfile                  # Python 3.12-slim, uvicorn on 8000
├── docker-compose.yml          # Redis Stack, Postgres, Prometheus, Grafana
├── requirements.txt
└── .env.example
```

---

## The Six Agents

Each agent follows the same pattern: system prompt → user message from state → Claude API call → JSON parse → partial state update returned to LangGraph.

### 1. Monitoring Agent
**Reads:** `pipeline_name`, `pipeline_metrics`, `raw_logs`  
**Writes:** `failure_detected`, `failure_type`, `failure_summary`  
**Router:** no failure → `END`; failure detected → `analysis_agent`

Classifies failures into 8 types: `schema_drift`, `latency_spike`, `pipeline_crash`, `disk_full`, `out_of_memory`, `deadlock`, `replication_lag`, `data_quality`

### 2. Analysis Agent
**Reads:** monitoring outputs + full pipeline data  
**Writes:** `root_cause`, `affected_components`, `diagnosis_confidence`

Goes deeper than detection — reasons about *why* the failure occurred, names specific components, and rates its own confidence.

### 3. Planning Agent
**Reads:** analysis outputs + failure context  
**Writes:** `recovery_plan` (ordered list), `estimated_risk` (`low` | `high`)

Generates concrete, executable steps. Explicitly prompted to flag any step involving schema changes, data deletion, or service restarts as high risk.

### 4. Security Agent
**Reads:** recovery plan + failure context  
**Writes:** `risk_level`, `approved`, `approval_reason`

Re-evaluates Planning's risk estimate independently and can override it. Python hard gate: `if risk_level == "high": approved = False` — LLM cannot override this.

### 5. Execution Agent
**Reads:** `recovery_plan`, `approved`  
**Writes:** `actions_taken`, `execution_status`, `execution_errors`

Two phases: (1) simulate each recovery step with probabilistic outcomes per action type, (2) Claude interprets and summarizes the results. Simulated in Ring 1–3; designed for real subprocess/API calls in production.

### 6. Audit Agent
**Reads:** entire accumulated state  
**Writes:** `audit_log`, `completed_at` + PostgreSQL row

Always runs last regardless of path taken. Writes a complete incident report and persists it to the `incidents` table. Outcome: `resolved` | `requires_human` | `failed`.

---

## The 8 Failure Scenarios

| Scenario | Pipeline | What Happens |
|---|---|---|
| `schema_drift` | etl_orders_pipeline | Column dropped from source table — schema validator aborts immediately, 0 rows committed |
| `latency_spike` | etl_inventory_pipeline | Progressive slowdown across batches — timeout after 45s, 1,200/5,000 rows committed |
| `pipeline_crash` | etl_payments_pipeline | DB completely unreachable — connection refused, all 3 retries exhausted |
| `disk_full` | etl_analytics_pipeline | DB runs out of disk mid-run — `No space left on device` on WAL write, 3,400/15,000 committed |
| `out_of_memory` | etl_reporting_pipeline | OOM killer terminates worker process (signal 9) — 7,800/50,000 rows committed |
| `deadlock` | etl_user_events_pipeline | Two transactions block each other — PostgreSQL kills one, retries also deadlock |
| `replication_lag` | etl_customer_pipeline | Read replica 8m47s behind primary — SLA violated, pipeline aborted to protect data integrity |
| `data_quality` | etl_transactions_pipeline | Source data corrupt (nulls, duplicates, negatives) — error rate 39.6% exceeds 10% threshold |

---

## Getting Started

### Requirements
- Python 3.11+
- Docker Desktop (with Kubernetes enabled)
- Anthropic API key
- Azure account (optional — for Azure ingest/execute slice)

### Installation

```bash
git clone https://github.com/yourusername/multi-agent-infra-recovery
cd multi-agent-infra-recovery

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Environment Setup

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```env
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Local infrastructure (matches docker-compose.yml ports)
POSTGRES_HOST=localhost
POSTGRES_PORT=5434
POSTGRES_DB=infra_ops
POSTGRES_USER=admin
POSTGRES_PASSWORD=password
REDIS_URL=redis://localhost:6380

# Azure (optional — for real cloud telemetry)
AZURE_FUNCTION_URL=https://your-function-app.azurewebsites.net/api/remediate
AZURE_FUNCTION_KEY=your-function-key
APPLICATIONINSIGHTS_APP_ID=your-app-id
APPLICATIONINSIGHTS_API_KEY=your-api-key
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=...  # for emit_failures only
```

### Start the Infrastructure

```bash
# Start Redis, Postgres, Prometheus, Grafana
docker compose up -d

# Apply the database schema (first time only)
# Linux/Mac:
docker exec -i <postgres-container> psql -U admin -d infra_ops < db/schema.sql
# Windows PowerShell:
Get-Content db/schema.sql | docker exec -i <postgres-container> psql -U admin -d infra_ops
```

### Run

**CLI (quick test, no pause/resume):**
```bash
python main.py pipeline_crash
python main.py schema_drift
python main.py                    # random scenario
```

**API + Dashboard (full human-in-the-loop):**
```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` for the operator dashboard.  
Open `http://localhost:8000/docs` for the Swagger UI.

**Grafana:** `http://localhost:3000` (admin/admin)  
**Prometheus:** `http://localhost:9090`

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Operator dashboard |
| `POST` | `/run` | Start recovery run — body: `{ "scenario": "schema_drift", "source": "mock" }` |
| `POST` | `/run` | Azure ingest — body: `{ "source": "azure" }` |
| `POST` | `/approve/{thread_id}` | Human approves high-risk plan — resumes graph + triggers Azure Function |
| `POST` | `/reject/{thread_id}` | Human rejects plan — graph resumes to audit only |
| `GET` | `/status/{thread_id}` | Check run state (pending / completed) |
| `GET` | `/incidents` | Last 50 incidents from PostgreSQL |
| `GET` | `/stats` | Aggregate counts (total, resolved, failed, human approved/rejected) |
| `GET` | `/metrics` | Prometheus exposition format |
| `GET` | `/metrics/summary` | Live metric bars for dashboard |
| `GET` | `/health` | Health check |

---

## Azure Integration

### Ingest (Real Cloud Telemetry)

```bash
# 1. Seed App Insights with test failure events
python azure/emit_failures.py

# 2. Wait 2-3 minutes for indexing, then trigger an Azure-sourced run
# POST /run with { "source": "azure" }
```

The ingest module queries App Insights via KQL REST API using an API key — no Azure AD or service principal required. Returns the same `AgentState` shape as the mock simulator so agents are completely unaware of the data source.

### Execute (Post-Approval Azure Function)

When a human approves a high-risk plan, the `/approve` endpoint automatically POSTs the recovery context to the deployed Azure Function, which logs the remediation event to App Insights. The Function response is included in the API response under `azure_execute`.

---

## Kubernetes Deployment

```bash
# Build the image
docker build -t infra-recovery-api:latest .

# Deploy to local K8s cluster
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml      # add your real API keys first
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

# Watch the pod start
kubectl get pods -w

# Access at http://localhost:8000 (same as local uvicorn)
```

Note: Data services (Postgres, Redis, Prometheus, Grafana) remain on Docker Compose. The K8s pod reaches them via `host.docker.internal`.

---

## Observability

### Prometheus Metrics

| Metric | Type | Description |
|---|---|---|
| `infra_recovery_runs_total` | Counter | Total runs by scenario and status |
| `infra_recovery_human_decisions_total` | Counter | Approve/reject counts |
| `infra_recovery_pending_approvals` | Gauge | Currently paused runs |
| `infra_recovery_agent_steps_total` | Counter | Per-agent step counts |
| `infra_recovery_graph_run_seconds` | Histogram | Run duration by endpoint |
| `infra_recovery_api_errors_total` | Counter | Errors by endpoint |

### Grafana Dashboards

- **Agent Recovery** — run lifecycle, agent step counts, approval rates, error rates (Prometheus)
- **Incident History** — outcome breakdown, failure type distribution, resolution timeline (PostgreSQL)

---

## What Is Real vs Simulated

| Layer | Real? | Notes |
|---|---|---|
| LLM reasoning (all 6 agents) | ✅ Real | Actual Anthropic API calls — costs tokens |
| LangGraph orchestration | ✅ Real | Real graph, real interrupt/resume with Redis |
| Human approval workflow | ✅ Real | FastAPI + Redis checkpointing |
| PostgreSQL audit log | ✅ Real | 16+ incident records persisted |
| Prometheus + Grafana | ✅ Real | Real metrics stack |
| Azure App Insights ingest | ✅ Real | KQL query against live App Insights resource |
| Azure Function execute | ✅ Real | Deployed HTTP function, called on every approval |
| Failure input (mock) | 🔵 Simulated | Scripted logs/metrics — no real pipelines |
| Execution agent steps | 🔵 Simulated | `simulate_action()` — probabilistic, not real infra |
| OpenTelemetry tracing | 📋 Planned | Architecture documented, not implemented |

---

## Capabilities

- Full 6-agent pipeline runs end-to-end on 8 simulated failure scenarios
- Real Azure Application Insights telemetry ingestion via KQL REST API
- LangGraph graph pause/resume with Redis Stack checkpointing
- Human approval gate — high-risk plans never auto-execute
- Azure Function triggered on every human approval (post-approval remediation hook)
- Per-agent Prometheus metrics with Grafana dashboards
- PostgreSQL audit trail — 16 incident records with full JSONB report storage
- Kubernetes deployment with readiness/liveness probes
- Operator dashboard with approve/reject UI, incident history, live metric bars

## Roadmap

- Real execution — replace `simulate_action()` with subprocess/API calls for actual infrastructure actions
- OpenTelemetry distributed tracing across all agent calls
- Azure source toggle in dashboard UI (currently mock-only dropdown)
- Additional failure scenarios — certificate expiry, rate limiting, memory leak
- Alert integration — PagerDuty/Slack notification on high-risk plan detection
- Multi-pipeline monitoring — run Monitoring Agent continuously, not on-demand

---

## Why This Project

Modern infrastructure generates more incidents than human operators can triage manually. This project explores what safe, auditable AI automation looks like in practice — not just wrapping an LLM around a problem, but building a system where:

- Agents have clear, scoped responsibilities and never exceed them
- Every decision is logged with full reasoning traceability
- Humans remain in control of anything destructive
- The system fails safely — escalating rather than guessing

The architecture mirrors how real AIOps platforms are designed: specialized agents, shared state, conditional routing, and human oversight as a first-class feature rather than an afterthought.

---

## Demo

A full end-to-end run: Azure telemetry ingested → 6 agents reason autonomously → human approves high-risk plan → execution runs → audit saved to PostgreSQL.

# Agent Pipeline — Full Run

<img width="1468" height="275" alt="image" src="https://github.com/user-attachments/assets/33bd2db6-24e0-4572-81dc-85731ca66360" />

<img width="2538" height="324" alt="image" src="https://github.com/user-attachments/assets/a46f092f-0336-4594-83ef-503cea3b9f36" />

<img width="2005" height="493" alt="image" src="https://github.com/user-attachments/assets/ee7bcf4a-5ae0-4d17-8225-120875d2f4a1" />

<img width="2547" height="239" alt="image" src="https://github.com/user-attachments/assets/2280880a-b918-4a61-8fcf-b6ff08065b6c" />

<img width="2529" height="154" alt="image" src="https://github.com/user-attachments/assets/75c31f9a-c610-491b-a02b-5cdd824a55fa" />

<img width="2536" height="278" alt="image" src="https://github.com/user-attachments/assets/cb317cfb-c647-48a9-91d1-c61b62284b99" />

<img width="1337" height="806" alt="image" src="https://github.com/user-attachments/assets/cb3270f4-6229-4407-a2ff-f063fdbe1081" />

<img width="2544" height="897" alt="image" src="https://github.com/user-attachments/assets/9b6c99d9-5b2e-4efb-82ba-d676df344a32" />

All 6 agents firing in sequence. The Security Agent flags a high-risk plan and the graph pauses at human approval.

# Operator Dashboard — Pending Approval

<img width="1159" height="1091" alt="image" src="https://github.com/user-attachments/assets/6abcf85b-3586-4474-8c29-2a44ba604146" />

<img width="1124" height="1134" alt="image" src="https://github.com/user-attachments/assets/077d075d-8fc9-4831-ada6-e872594f3f9f" />

The ops dashboard surfaces the recovery plan with approve/reject controls. No terminal access needed for the human reviewer.

# Incident Report + PostgreSQL Audit

<img width="2549" height="484" alt="image" src="https://github.com/user-attachments/assets/162eb73d-4263-4320-b702-ce355d65de38" />

<img width="1015" height="129" alt="image" src="https://github.com/user-attachments/assets/f407c344-3613-4a80-8a1d-3c06560f0199" />

The Audit Agent writes a structured incident report and persists it to PostgreSQL. [Database] Incident saved → id: 16

# Grafana Observability Dashboard

<img width="1201" height="991" alt="image" src="https://github.com/user-attachments/assets/c237147a-153a-4033-95df-c2a6e89a764e" />

6 custom Prometheus metrics — per-agent step counters, run lifecycle histograms, and approval gauges.

Video Walkthrough

https://www.loom.com/share/f0b5b086d838485d8791760b2bffa519

3-minute walkthrough: Azure ingest → agent reasoning → human approval → execution → audit log
