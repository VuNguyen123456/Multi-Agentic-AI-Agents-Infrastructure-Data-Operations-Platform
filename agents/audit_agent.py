import json
from datetime import datetime
from anthropic import Anthropic
from dotenv import load_dotenv
import os

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

client = Anthropic()

AUDIT_SYSTEM_PROMPT = """
You are the Audit Agent in an autonomous infrastructure operations system.

You are the final agent in the pipeline. You receive the complete record of everything
that happened during this incident response — detection, diagnosis, planning, security
review, and execution (if it happened).

Your job is to write a clear, structured incident report that an engineer could read
to fully understand what happened and what was done.

You must respond with ONLY a JSON object. No explanation, no markdown, no extra text.

Response format:
{
  "incident_summary": "2-3 sentence overview of the entire incident and response",
  "timeline": [
    "Monitoring: what was detected",
    "Analysis: what root cause was found",
    "Planning: what recovery plan was generated",
    "Security: what the risk decision was",
    "Execution: what was done (or why nothing was executed)"
  ],
  "outcome": "resolved" | "requires_human" | "failed",
  "recommendations": ["one actionable recommendation for preventing this in future"]
}

Rules:
- incident_summary must be factual and concise — no filler
- timeline must have exactly 5 entries, one per agent stage
- outcome is "resolved" if execution_status is "success"
- outcome is "requires_human" if approved is false (security rejected or human approval needed)
- outcome is "failed" if execution_status is "partial" or "failed"
- recommendations should be specific and preventative — not generic advice
""".strip()


def build_user_message(state: dict) -> str:
    """
    Dumps the entire accumulated state into a structured summary for Claude.
    The Audit Agent gets more context than any other agent — it sees everything.
    """
    plan_text = "Not generated"
    if state.get("recovery_plan"):
        plan_text = "\n".join(
            f"  {i+1}. {step}" for i, step in enumerate(state["recovery_plan"])
        )

    actions_text = "No actions executed"
    if state.get("actions_taken"):
        actions_text = "\n".join(f"  - {a}" for a in state["actions_taken"])

    errors_text = "None"
    if state.get("execution_errors"):
        errors_text = "\n".join(f"  - {e}" for e in state["execution_errors"])

    return f"""
=== INCIDENT REPORT DATA ===

PIPELINE
  Name: {state.get("pipeline_name")}
  Failure type: {state.get("failure_type")}

MONITORING AGENT
  Failure detected: {state.get("failure_detected")}
  Summary: {state.get("failure_summary")}

ANALYSIS AGENT
  Root cause: {state.get("root_cause")}
  Affected components: {", ".join(state.get("affected_components") or [])}
  Confidence: {state.get("diagnosis_confidence")}

PLANNING AGENT
  Estimated risk: {state.get("estimated_risk")}
  Recovery plan:
{plan_text}

SECURITY AGENT
  Final risk level: {state.get("risk_level")}
  Approved: {state.get("approved")}
  Reason: {state.get("approval_reason")}

EXECUTION AGENT
  Status: {state.get("execution_status", "not executed")}
  Actions taken:
{actions_text}
  Errors:
{errors_text}

Write the incident report and return your JSON response.
""".strip()


def parse_claude_response(response_text: str) -> dict:
    try:
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        return json.loads(cleaned.strip())
    except json.JSONDecodeError:
        return {
            "incident_summary": f"Audit parse error: {response_text[:100]}",
            "timeline": ["Parse error — manual review required"],
            "outcome": "failed",
            "recommendations": ["Review audit agent logs manually"]
        }


def audit_agent(state: dict) -> dict:
    """
    The Audit Agent node function. Always the last node to run.

    Reads:  everything — the entire accumulated state
    Writes: audit_log, completed_at
    Also:   saves the full incident record to PostgreSQL
    """
    print(f"\n[Audit Agent] Writing incident report for: {state.get('pipeline_name')}")

    user_message = build_user_message(state)

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        system=AUDIT_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": user_message}
        ]
    )

    response_text = response.content[0].text
    print(f"[Audit Agent] Raw response: {response_text}")

    result       = parse_claude_response(response_text)
    completed_at = datetime.now().isoformat()

    # Pretty print the full report
    print(f"\n{'='*50}")
    print(f"INCIDENT REPORT — {state.get('pipeline_name')}")
    print(f"{'='*50}")
    print(f"Summary:  {result['incident_summary']}")
    print(f"Outcome:  {result['outcome'].upper()}")
    print(f"\nTimeline:")
    for entry in result.get("timeline", []):
        print(f"  → {entry}")
    print(f"\nRecommendations:")
    for rec in result.get("recommendations", []):
        print(f"  • {rec}")
    print(f"\nCompleted at: {completed_at}")
    print(f"{'='*50}\n")

    # ── Save to PostgreSQL ─────────────────────────────────────────────────────
    # Wrapped in try/except so a DB failure never crashes the agent
    try:
        import sys
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db.database import save_incident
        thread_id   = state.get("thread_id")
        incident_id = save_incident(state, result, thread_id=thread_id)
        print(f"[Audit Agent] Incident persisted → PostgreSQL id: {incident_id}")
    except Exception as e:
        print(f"[Audit Agent] Warning: could not save to PostgreSQL: {e}")

    return {
        "audit_log":     json.dumps(result, indent=2),
        "completed_at":  completed_at,
        "current_agent": "audit_agent"
    }


# ── LOCAL TEST ─────────────────────────────────────────────────────────────────
# Test two paths: the full success path and the rejected path.

if __name__ == "__main__":
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from simulator.failure_sim import generate_failure

    print("=" * 50)
    print("Testing Audit Agent in isolation")
    print("=" * 50)

    # ── Path A: Full success (execution ran and succeeded) ─────────────────────
    print("\n--- Path A: Execution succeeded ---")
    state_success = generate_failure("pipeline_crash")
    state_success.update({
        "failure_detected": True,
        "failure_type": "pipeline_crash",
        "failure_summary": "Pipeline failed to connect to payments_db after 3 retries.",
        "root_cause": "PostgreSQL server payments_db on port 5432 was unreachable.",
        "affected_components": ["payments_db", "etl_payments_pipeline"],
        "diagnosis_confidence": "high",
        "recovery_plan": [
            "Step 1: Check PostgreSQL service status",
            "Step 2: Verify network connectivity to payments_db:5432",
            "Step 3: Review PostgreSQL logs",
            "Step 4: Run health check on connection pool",
            "Step 5: Re-run etl_payments_pipeline",
        ],
        "estimated_risk": "low",
        "risk_level": "low",
        "approved": True,
        "approval_reason": "All steps are read-only checks and a pipeline re-run.",
        "actions_taken": [
            "Checked PostgreSQL service status — service running normally",
            "Verified network connectivity to payments_db:5432 — reachable",
            "Reviewed PostgreSQL logs — no critical issues found",
            "Ran health check on connection pool — pool healthy",
            "Re-ran etl_payments_pipeline — completed successfully",
        ],
        "execution_status": "success",
        "execution_errors": [],
    })
    audit_agent(state_success)

    # ── Path B: Security rejected (high risk, nothing executed) ────────────────
    print("\n--- Path B: Security rejected ---")
    state_rejected = generate_failure("schema_drift")
    state_rejected.update({
        "failure_detected": True,
        "failure_type": "schema_drift",
        "failure_summary": "Pipeline aborted — customer_email column missing from orders table.",
        "root_cause": "The customer_email column was removed from the orders table.",
        "affected_components": ["orders_db", "orders table", "etl_orders_pipeline"],
        "diagnosis_confidence": "high",
        "recovery_plan": [
            "Step 1: Verify current schema of orders table",
            "Step 2: Investigate recent DDL changes",
            "Step 3: Restore customer_email column if removal was accidental",
            "Step 4: Update pipeline schema validation config",
            "Step 5: Re-run etl_orders_pipeline",
        ],
        "estimated_risk": "high",
        "risk_level": "high",
        "approved": False,
        "approval_reason": "Step 3 proposes schema modification — requires human approval.",
        "actions_taken": None,
        "execution_status": None,
        "execution_errors": None,
    })
    audit_agent(state_rejected)