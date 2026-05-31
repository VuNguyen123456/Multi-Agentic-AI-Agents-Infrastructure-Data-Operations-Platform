# Multi-Agent Infrastructure Recovery System

An autonomous AI system that detects, diagnoses, and recovers from data pipeline failures — with human oversight for high-risk operations.

Built with LangGraph and Claude (Anthropic) as a demonstration of production-grade AI orchestration applied to real infrastructure operations problems.

---

## What It Does

When a data pipeline fails, this system autonomously:

1. **Detects** the failure and classifies its type (schema drift, latency spike, crash)
2. **Diagnoses** the root cause by reasoning over logs and metrics
3. **Plans** a concrete, ordered recovery procedure
4. **Assesses risk** and either auto-approves or escalates to a human
5. **Executes** the recovery steps if approved
6. **Logs** a full structured incident report regardless of outcome

No human intervention required for low-risk recoveries. High-risk actions (schema changes, service restarts, data modifications) are held for explicit human approval before anything executes.

---

## Architecture

Six specialized AI agents, each with a single responsibility, orchestrated by LangGraph:

```
[Monitoring Agent]  →  detects failures, classifies type
        ↓
[Analysis Agent]    →  finds root cause from logs and metrics
        ↓
[Planning Agent]    →  generates ordered recovery steps + risk estimate
        ↓
[Security Agent]    →  validates risk, makes final approval decision
        ↓
   low risk ──────────────────────────────────────────→ [Execution Agent]
   high risk → pause → wait for human approval via API → [Execution Agent]
                                                                ↓
                                                        [Audit Agent]  →  logs full incident report
```

LangGraph manages state across all agents, handles conditional routing (auto-execute vs. human escalation), and will support mid-run pause/resume for human-in-the-loop approval.

Each agent is a focused Claude API call with a scoped system prompt. No agent knows about the others — they communicate exclusively through shared state.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent Framework | LangGraph |
| LLM | Claude (Anthropic API) |
| Backend / Approval API | FastAPI |
| State Persistence | Redis |
| Database | PostgreSQL |
| Observability | Prometheus + Grafana |
| Infrastructure | Docker |
| Tracing | OpenTelemetry *(planned)* |

---

## Project Structure

```
project/
├── agents/
│   ├── monitoring_agent.py     # failure detection + classification
│   ├── analysis_agent.py       # root cause analysis
│   ├── planning_agent.py       # recovery plan generation
│   ├── security_agent.py       # risk validation + approval logic
│   ├── execution_agent.py      # recovery execution + result tracking
│   └── audit_agent.py          # incident report generation
├── orchestrator/
│   └── graph.py                # LangGraph graph — wires all agents together
├── simulator/
│   └── failure_sim.py          # simulates pipeline failures for local testing
├── api/
│   └── main.py                 # FastAPI human approval endpoint (in progress)
├── state.py                    # shared AgentState TypedDict
├── main.py                     # entry point
└── docker-compose.yml          # PostgreSQL + Redis (in progress)
```

---

## Getting Started

**Requirements:** Python 3.11+, an Anthropic API key

```bash
git clone https://github.com/yourusername/multi-agent-infra-recovery
cd multi-agent-infra-recovery

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the project root (see `.env.example`):

```
ANTHROPIC_API_KEY=sk-ant-...
REDIS_URL=redis://localhost:6380
POSTGRES_PORT=5434
```

Start infrastructure and the API:

```powershell
docker compose up -d
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Apply the database schema once (first run):

```powershell
docker exec -i agenticaiproject-postgres-1 psql -U admin -d infra_ops < db/schema.sql
```

Run a simulated recovery (CLI, no API):

```bash
python main.py pipeline_crash    # database unreachable
python main.py schema_drift      # column missing from table
python main.py latency_spike     # pipeline timeout
python main.py                   # random scenario
```

---

## Failure Scenarios

Three failure types are currently simulated:

**Schema Drift** — A column is dropped from a source database table. The ETL pipeline aborts immediately on schema validation. Recovery requires schema investigation and either restoring the column or updating the pipeline config — flagged as high risk, requires human approval.

**Latency Spike** — A pipeline runs but degrades progressively across batches, eventually timing out with a partial commit. Root cause is typically database resource contention or missing indexes. Recovery involves DB diagnostics and potential index creation — flagged as high risk.

**Pipeline Crash** — The source database is unreachable. All connection retries exhausted, zero rows committed. Recovery involves connectivity checks and service restart — service restart is flagged as high risk; read-only diagnostics are auto-approved.

---

## Observability

Three layers work together:

| Layer | Purpose | URL |
|-------|---------|-----|
| **HTML dashboard** | Human approval workflow + incident table + embedded Grafana charts | http://localhost:8000/ |
| **Prometheus** | Time-series metrics (run rates, agent steps, latency) | http://localhost:9090 |
| **Grafana** | Charts for API health + Postgres incident trends | http://localhost:3000 (admin / admin) |

The FastAPI app exposes Prometheus metrics at `GET /metrics`. Prometheus scrapes it every 15 seconds via `host.docker.internal:8000` (API runs on the host, not in Docker). The main dashboard at `/` embeds key Grafana panels so you can see live metrics without writing PromQL — use **Open full Grafana** for deeper exploration.

After starting the stack, run a recovery via `POST /run` and optionally approve/reject — counters like `infra_recovery_runs_total` and `infra_recovery_agent_steps_total` will appear in Prometheus and the **Agent Recovery — Metrics** Grafana dashboard.

---

## Current Capabilities

- Full 6-agent pipeline runs end-to-end on simulated failures
- LangGraph conditional routing (auto-execute vs. escalate to audit)
- Each agent tested independently before graph integration
- Structured incident reports generated for every run
- Graceful handling of partial execution failures

## Roadmap

- Human approval API with Redis checkpointing (pause/resume via `/approve` and `/reject`)
- Persistent audit log in PostgreSQL
- Prometheus metrics + Grafana dashboards for agent activity and incident trends
- HTML ops dashboard for approvals and incident history
- **Additional failure scenarios** — disk full, memory exhaustion, replication lag

---

## Why This Project

Modern infrastructure generates more incidents than human operators can triage manually. This project explores what safe, auditable AI automation looks like in practice — not just wrapping an LLM around a problem, but building a system where agents have clear responsibilities, every decision is logged, and humans remain in control of anything destructive.

The design prioritizes safety over speed: the system will always escalate rather than guess on high-risk actions, and the audit agent ensures full traceability of every reasoning step.
