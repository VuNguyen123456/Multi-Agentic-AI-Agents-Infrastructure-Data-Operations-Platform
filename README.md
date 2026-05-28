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
| Backend / Approval API | FastAPI *(in progress)* |
| State Persistence | Redis *(in progress)* |
| Database | PostgreSQL *(in progress)* |
| Observability | Prometheus + Grafana *(planned)* |
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
pip install langgraph langchain-anthropic python-dotenv
```

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Run a simulated recovery:

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

## Current Capabilities

- Full 6-agent pipeline runs end-to-end on simulated failures
- LangGraph conditional routing (auto-execute vs. escalate to audit)
- Each agent tested independently before graph integration
- Structured incident reports generated for every run
- Graceful handling of partial execution failures

## Roadmap

- **Human approval API** — FastAPI endpoint to pause the graph on high-risk plans and resume after human decision via `POST /approve` or `POST /reject`
- **State persistence** — Redis checkpointing so graph state survives between the pause and resume
- **Persistent audit log** — PostgreSQL storage for all incident reports and agent reasoning
- **Observability dashboard** — Grafana dashboard showing agent activity, incident history, and recovery outcomes in real time
- **Additional failure scenarios** — disk full, memory exhaustion, replication lag

---

## Why This Project

Modern infrastructure generates more incidents than human operators can triage manually. This project explores what safe, auditable AI automation looks like in practice — not just wrapping an LLM around a problem, but building a system where agents have clear responsibilities, every decision is logged, and humans remain in control of anything destructive.

The design prioritizes safety over speed: the system will always escalate rather than guess on high-risk actions, and the audit agent ensures full traceability of every reasoning step.
