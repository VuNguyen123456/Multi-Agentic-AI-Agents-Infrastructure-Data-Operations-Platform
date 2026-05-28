import json
from anthropic import Anthropic
from dotenv import load_dotenv
import os

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

client = Anthropic()


# ── THE PROMPT ─────────────────────────────────────────────────────────────────
# Planning Agent knows WHY it failed (from Analysis).
# Its job: generate a concrete, ordered, executable recovery plan.
# It also makes the first risk assessment — will this fix be safe or destructive?
#
# Key design decision: steps must be ACTIONABLE, not vague.
# Bad:  "fix the database"
# Good: "restart the payments_db Docker container and verify port 5432 is listening"

PLANNING_SYSTEM_PROMPT = """
You are the Planning Agent in an autonomous infrastructure operations system.

The Analysis Agent has diagnosed the root cause of a pipeline failure.
Your job is to generate a concrete, ordered, step-by-step recovery plan.

You must also estimate the risk level of executing this plan:
- "low"  → read-only checks, restarts, re-runs. Safe to auto-execute.
- "high" → schema changes, data deletion, config edits, rollbacks. Needs human approval.

You must respond with ONLY a JSON object. No explanation, no markdown, no extra text.

Response format:
{
  "recovery_plan": [
    "Step 1: specific action to take",
    "Step 2: specific action to take",
    "Step 3: specific action to take"
  ],
  "estimated_risk": "low" | "high"
}

Rules:
- Each step must be specific and executable by an engineer or an automated system
- Steps must be in the correct order — dependencies first
- 3 to 6 steps maximum
- estimated_risk is "high" if ANY step involves: modifying schema, deleting data, changing configs, rolling back migrations, or stopping production services
- estimated_risk is "low" if steps are limited to: health checks, service restarts, pipeline re-runs, log inspection
- Do not invent steps that aren't justified by the root cause
""".strip()


def build_user_message(state: dict) -> str:
    """
    Gives the Planning Agent the full picture so far:
    what failed, why it failed, which components are affected.
    """
    return f"""
Pipeline name: {state["pipeline_name"]}

Failure type: {state["failure_type"]}
Monitoring summary: {state["failure_summary"]}

Root cause (from Analysis Agent): {state["root_cause"]}
Affected components: {", ".join(state.get("affected_components") or [])}
Diagnosis confidence: {state["diagnosis_confidence"]}

Generate a recovery plan and return your JSON response.
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
            "recovery_plan": [f"Parse error — manual review required: {response_text[:100]}"],
            "estimated_risk": "high"   # Default to high risk on parse failure — always safe to be cautious
        }


def planning_agent(state: dict) -> dict:
    """
    The Planning Agent node function.

    Reads:  failure_type, failure_summary, root_cause, affected_components, diagnosis_confidence
    Writes: recovery_plan, estimated_risk
    """
    print(f"\n[Planning Agent] Generating recovery plan for: {state['failure_type']}")

    user_message = build_user_message(state)

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,      # Plans can be detailed — give it room
        system=PLANNING_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": user_message}
        ]
    )

    response_text = response.content[0].text
    print(f"[Planning Agent] Raw response: {response_text}")

    result = parse_claude_response(response_text)

    print(f"[Planning Agent] Estimated risk: {result['estimated_risk']}")
    print(f"[Planning Agent] Recovery steps:")
    for i, step in enumerate(result["recovery_plan"], 1):
        print(f"  {i}. {step}")

    # Return ONLY the fields this agent owns
    # LangGraph merges this partial update into the full state - then it's passed to the next agent (likely the Execution Agent)
    # Give Execution Agent the recovery plan and estimated risk
    # But next agent is the Security Agent, so we need to give it the recovery plan and estimated risk
    return {
        "recovery_plan":   result["recovery_plan"],
        "estimated_risk":  result["estimated_risk"],
        "current_agent":   "planning_agent"
    }


# ── LOCAL TEST ─────────────────────────────────────────────────────────────────
# State simulates monitoring + analysis both having already run.
# Planning receives the full accumulated state and generates the plan.

if __name__ == "__main__":
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from simulator.failure_sim import generate_failure

    # What state looks like after monitoring + analysis have both run
    prior_agent_outputs = {
        "schema_drift": {
            "failure_detected": True,
            "failure_type": "schema_drift",
            "failure_summary": "Pipeline aborted because the 'customer_email' column is missing from the orders table.",
            "root_cause": "The 'customer_email' column was removed from the source 'orders' table, causing schema validation to fail.",
            "affected_components": ["orders_db", "orders table", "etl_orders_pipeline", "schema_validation"],
            "diagnosis_confidence": "high",
        },
        "latency_spike": {
            "failure_detected": True,
            "failure_type": "latency_spike",
            "failure_summary": "Pipeline timed out after 45s, processing only 1200 of 5000 rows.",
            "root_cause": "Progressive degradation of inventory_db query performance, indicating database-side resource contention or missing indexes.",
            "affected_components": ["inventory_db", "etl_inventory_pipeline", "postgres_connection"],
            "diagnosis_confidence": "high",
        },
        "pipeline_crash": {
            "failure_detected": True,
            "failure_type": "pipeline_crash",
            "failure_summary": "Pipeline failed to connect to payments_db after exhausting all 3 retry attempts.",
            "root_cause": "PostgreSQL server 'payments_db' on port 5432 is unreachable — service is down or blocked.",
            "affected_components": ["payments_db", "etl_payments_pipeline", "postgres_connection"],
            "diagnosis_confidence": "high",
        },
    }

    print("=" * 50)
    print("Testing Planning Agent in isolation")
    print("=" * 50)

    for scenario in ["schema_drift", "latency_spike", "pipeline_crash"]:
        print(f"\n--- Scenario: {scenario} ---")
        state = generate_failure(scenario)
        state.update(prior_agent_outputs[scenario])
        result = planning_agent(state)
        print(f"Result: {json.dumps(result, indent=2)}")
        print()