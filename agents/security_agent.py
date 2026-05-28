import json
from anthropic import Anthropic
from dotenv import load_dotenv
import os

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

client = Anthropic()


# ── THE PROMPT ─────────────────────────────────────────────────────────────────
# Security Agent is the gatekeeper. It reads the full plan and makes the
# FINAL risk decision. It doesn't trust the Planning Agent's estimate blindly —
# it re-evaluates from scratch and can override it.
#
# Critical design: if risk_level is "high", approved is always False.
# The graph will pause and wait for human approval in Ring 2.
# In Ring 1, high risk = rejected, low risk = approved.

SECURITY_SYSTEM_PROMPT = """
You are the Security Agent in an autonomous infrastructure operations system.

The Planning Agent has generated a recovery plan and made an initial risk estimate.
Your job is to independently validate that risk assessment and make the FINAL approval decision.

You are the last line of defense before automated execution. Be conservative.

Risk classification rules (apply ALL of them):
HIGH risk if the plan includes ANY of:
- Modifying database schema (ADD/DROP/ALTER column, table, index)
- Deleting or truncating data
- Stopping or restarting production services
- Modifying configuration files
- Rolling back migrations or deployments
- Terminating running processes or queries
- Changes that cannot be easily undone

LOW risk if ALL steps are limited to:
- Read-only inspection (checking status, reading logs, running EXPLAIN)
- Health checks and connectivity tests
- Re-running a failed pipeline with no changes
- Monitoring and observability queries

You must respond with ONLY a JSON object. No explanation, no markdown, no extra text.

Response format:
{
  "risk_level": "low" | "high",
  "approved": true | false,
  "approval_reason": "one sentence explaining the decision"
}

Rules:
- If risk_level is "high": approved must always be false
- If risk_level is "low": approved must always be true
- approval_reason must clearly state what specific step drove the risk decision
- You may override the Planning Agent's estimated_risk if you disagree
""".strip()


def build_user_message(state: dict) -> str:
    """
    Gives the Security Agent everything it needs to make its decision:
    the full plan, the planner's risk estimate, and the context of what broke.
    """
    plan_steps = "\n".join(
        f"  {i+1}. {step}" for i, step in enumerate(state.get("recovery_plan") or [])
    )

    return f"""
Pipeline name: {state["pipeline_name"]}
Failure type: {state["failure_type"]}
Root cause: {state["root_cause"]}

Planning Agent's risk estimate: {state["estimated_risk"]}

Recovery plan to evaluate:
{plan_steps}

Evaluate this plan and return your JSON approval decision.
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
        # On parse failure: reject and flag for human review
        return {
            "risk_level": "high",
            "approved": False,
            "approval_reason": f"Security agent parse error — auto-rejected for safety: {response_text[:100]}"
        }


def security_agent(state: dict) -> dict:
    """
    The Security Agent node function.

    Reads:  recovery_plan, estimated_risk, failure_type, root_cause
    Writes: risk_level, approved, approval_reason
    """
    print(f"\n[Security Agent] Evaluating recovery plan for: {state['failure_type']}")
    print(f"[Security Agent] Planner estimated risk: {state['estimated_risk']}")

    user_message = build_user_message(state)

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=256,
        system=SECURITY_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": user_message}
        ]
    )

    response_text = response.content[0].text
    print(f"[Security Agent] Raw response: {response_text}")

    result = parse_claude_response(response_text)

    # Safety enforcement: override approved if risk_level is high
    # Never trust the LLM to get this logic right 100% of the time
    if result["risk_level"] == "high":
        result["approved"] = False

    status = "✓ APPROVED — auto-executing" if result["approved"] else "✗ REJECTED — requires human approval"
    print(f"[Security Agent] Risk level: {result['risk_level']}")
    print(f"[Security Agent] Decision: {status}")
    print(f"[Security Agent] Reason: {result['approval_reason']}")

    # Return ONLY the fields this agent owns
    # LangGraph merges this partial update into the full state - then it's passed to the next agent (likely the Execution Agent)
    # Give Execution Agent the approved and approval reason
    return {
        "risk_level":      result["risk_level"],
        "approved":        result["approved"],
        "approval_reason": result["approval_reason"],
        "current_agent":   "security_agent"
    }


# ── ROUTER FUNCTION ────────────────────────────────────────────────────────────
# Called by LangGraph after security_agent runs.
# Low risk + approved → go straight to execution
# High risk → in Ring 1 we route to audit (rejected)
#             in Ring 2 this will pause and wait for human via FastAPI

def route_after_security(state: dict) -> str:
    if state["approved"]:
        print(f"[Router] Approved → routing to execution_agent")
        return "execution_agent"
    else:
        print(f"[Router] Rejected (risk: {state['risk_level']}) → routing to audit_agent")
        return "audit_agent"


# ── LOCAL TEST ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from simulator.failure_sim import generate_failure

    # Full accumulated state after monitoring + analysis + planning
    prior_agent_outputs = {
        "schema_drift": {
            "failure_detected": True,
            "failure_type": "schema_drift",
            "failure_summary": "Pipeline aborted because the 'customer_email' column is missing from the orders table.",
            "root_cause": "The 'customer_email' column was removed from the source 'orders' table, causing schema validation to fail.",
            "affected_components": ["orders_db", "orders table", "etl_orders_pipeline", "schema_validation"],
            "diagnosis_confidence": "high",
            "recovery_plan": [
                "Step 1: Verify the current schema of the 'orders' table in orders_db to confirm the 'customer_email' column is missing",
                "Step 2: Investigate recent DDL changes or migration logs to determine when and why 'customer_email' was removed",
                "Step 3: Coordinate with the team to determine if the column removal was intentional or accidental",
                "Step 4: If accidental, restore the 'customer_email' column to the orders table",
                "Step 5: Update the pipeline schema validation config if removal was intentional",
                "Step 6: Re-run the etl_orders_pipeline and verify successful completion",
            ],
            "estimated_risk": "high",
        },
        "latency_spike": {
            "failure_detected": True,
            "failure_type": "latency_spike",
            "failure_summary": "Pipeline timed out after 45s, processing only 1200 of 5000 rows.",
            "root_cause": "Progressive degradation of inventory_db query performance, indicating resource contention or missing indexes.",
            "affected_components": ["inventory_db", "etl_inventory_pipeline", "postgres_connection"],
            "diagnosis_confidence": "high",
            "recovery_plan": [
                "Step 1: Check active connections on inventory_db using pg_stat_activity",
                "Step 2: Run EXPLAIN ANALYZE on primary queries to identify missing indexes",
                "Step 3: If missing indexes found, create appropriate indexes on inventory tables",
                "Step 4: Terminate any non-critical long-running queries",
                "Step 5: Restart the postgres connection pool",
                "Step 6: Re-run etl_inventory_pipeline with monitoring enabled",
            ],
            "estimated_risk": "high",
        },
        "pipeline_crash": {
            "failure_detected": True,
            "failure_type": "pipeline_crash",
            "failure_summary": "Pipeline failed to connect to payments_db after exhausting all 3 retry attempts.",
            "root_cause": "PostgreSQL server 'payments_db' on port 5432 is unreachable — service is down or blocked.",
            "affected_components": ["payments_db", "etl_payments_pipeline", "postgres_connection"],
            "diagnosis_confidence": "high",
            "recovery_plan": [
                "Step 1: Check PostgreSQL service status on payments_db using systemctl status postgresql",
                "Step 2: If stopped, restart using systemctl restart postgresql and verify port 5432",
                "Step 3: Verify network connectivity from ETL host to payments_db:5432",
                "Step 4: Check firewall rules to ensure port 5432 is not blocked",
                "Step 5: Review PostgreSQL logs for errors",
                "Step 6: Re-run etl_payments_pipeline and monitor for successful connection",
            ],
            "estimated_risk": "low",
        },
    }

    print("=" * 50)
    print("Testing Security Agent in isolation")
    print("=" * 50)

    for scenario in ["schema_drift", "latency_spike", "pipeline_crash"]:
        print(f"\n--- Scenario: {scenario} ---")
        state = generate_failure(scenario)
        state.update(prior_agent_outputs[scenario])
        result = security_agent(state)

        # Also show what the router would do
        next_node = route_after_security({**state, **result})
        print(f"[Router] Next node: {next_node}")
        print(f"Result: {json.dumps(result, indent=2)}")
        print()