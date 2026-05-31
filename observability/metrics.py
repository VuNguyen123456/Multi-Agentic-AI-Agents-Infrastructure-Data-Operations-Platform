"""Prometheus metrics for the agent recovery API and LangGraph pipeline."""

from prometheus_client import Counter, Gauge, Histogram

# ── API / run lifecycle ────────────────────────────────────────────────────────
RUNS_TOTAL = Counter(
    "infra_recovery_runs_total",
    "Recovery runs started via the API",
    ["scenario", "status"],
)

HUMAN_DECISIONS_TOTAL = Counter(
    "infra_recovery_human_decisions_total",
    "Human approve/reject decisions",
    ["decision"],
)

PENDING_APPROVALS = Gauge(
    "infra_recovery_pending_approvals",
    "Runs currently waiting for human approval",
)

API_ERRORS_TOTAL = Counter(
    "infra_recovery_api_errors_total",
    "API handler errors",
    ["endpoint"],
)

# ── LangGraph agent activity ───────────────────────────────────────────────────
AGENT_STEPS_TOTAL = Counter(
    "infra_recovery_agent_steps_total",
    "LangGraph node executions (one per agent step)",
    ["agent"],
)

GRAPH_RUN_DURATION = Histogram(
    "infra_recovery_graph_run_seconds",
    "End-to-end graph execution time",
    ["endpoint"],
    buckets=(1, 2, 5, 10, 20, 30, 60, 90, 120, 180, 300),
)
