from typing import TypedDict, Optional, List
from datetime import datetime

# The shared memory of the entire system. All 6 agents receive a copy of this dictionary
# Perform it's task and return updates into this dictionary
# LangGraph merges those updates back automatically
# So no agent talk directly, but all of them talk though state

class AgentState(TypedDict):
    # ── PIPELINE INPUT ─────────────────────────────────────────────────────────
    # Raw data injected by the simulator at startup.
    # The Monitoring Agent reads this to decide if something is wrong.
    input_scenario: Optional[str]          # scenario key from failure_sim (e.g. disk_full)
    pipeline_name: str          # e.g. "etl_orders_pipeline"
    pipeline_metrics: dict      # latency, row counts, error rates, etc.
    raw_logs: List[str]         # last N log lines from the pipeline

    # ── MONITORING AGENT OUTPUT ────────────────────────────────────────────────
    # Written by the Monitoring Agent, read by the conditional edge router
    # to decide: go to Analysis, or stop (nothing wrong).
    failure_detected: bool                  # True = something is wrong
    failure_type: Optional[str]             # schema_drift | latency_spike | pipeline_crash | disk_full | ...
    failure_summary: Optional[str]          # One-line human-readable summary

    # ── ANALYSIS AGENT OUTPUT ─────────────────────────────────────────────────
    # Written by the Analysis Agent after reading logs + metrics.
    # The Planning Agent uses this to generate a recovery plan.
    root_cause: Optional[str]               # What actually caused the failure
    affected_components: Optional[List[str]] # e.g. ["orders_table", "schema_validator"]
    diagnosis_confidence: Optional[str]     # "high" | "medium" | "low"

    # ── PLANNING AGENT OUTPUT ─────────────────────────────────────────────────
    # Written by the Planning Agent.
    # The Security Agent reads this to assess risk.
    recovery_plan: Optional[List[str]]      # Ordered list of recovery steps
    estimated_risk: Optional[str]           # "low" | "high" (planner's first guess)

    # ── SECURITY AGENT OUTPUT ─────────────────────────────────────────────────
    # Written by the Security Agent.
    # The Execution Agent only runs if approved = True.
    risk_level: Optional[str]               # "low" | "high" (final verdict)
    approved: Optional[bool]                # True = safe to execute
    approval_reason: Optional[str]          # Why it was approved or rejected

    # ── HUMAN APPROVAL (Ring 2) ───────────────────────────────────────────────
    # Left empty in Ring 1. Will be filled via FastAPI in Ring 2
    # when the Security Agent flags risk_level = "high".
    human_approved: Optional[bool]          # Set externally via API
    human_notes: Optional[str]              # Optional message from the human

    # ── EXECUTION AGENT OUTPUT ────────────────────────────────────────────────
    # Written by the Execution Agent after running the recovery steps.
    actions_taken: Optional[List[str]]      # What was actually done
    execution_status: Optional[str]         # "success" | "partial" | "failed"
    execution_errors: Optional[List[str]]   # Any errors encountered

    # ── AUDIT AGENT OUTPUT ────────────────────────────────────────────────────
    # Written by the Audit Agent — the final node in the graph.
    audit_log: Optional[str]                # Full structured summary of the run
    completed_at: Optional[str]             # ISO timestamp of completion

    # ── GRAPH CONTROL ─────────────────────────────────────────────────────────
    # Used by conditional edges to route between nodes.
    # Agents should NOT write to these — only the router functions do.
    current_agent: Optional[str]            # Which agent just ran (for logging)
    error_message: Optional[str]            # If something crashed unexpectedly