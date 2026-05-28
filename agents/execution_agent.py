import json
import time
import random
from anthropic import Anthropic
from dotenv import load_dotenv
import os

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

client = Anthropic()


# ── SIMULATED ACTION EXECUTOR ──────────────────────────────────────────────────
# In Ring 1, we don't have real infrastructure to touch.
# This simulates what happens when each recovery step runs.
# Ring 3 would replace this with real Docker/DB/shell commands.
#
# Each action has a realistic success rate — some steps are risky and can fail.
# This lets us test partial failure handling (some steps pass, some fail).

ACTION_OUTCOMES = {
    "check":     {"success_rate": 0.95, "duration": 0.5},   # health checks almost always work
    "verify":    {"success_rate": 0.95, "duration": 0.5},
    "inspect":   {"success_rate": 0.95, "duration": 0.4},
    "review":    {"success_rate": 0.95, "duration": 0.4},
    "run":       {"success_rate": 0.85, "duration": 1.2},   # re-runs can fail
    "restart":   {"success_rate": 0.80, "duration": 2.0},   # restarts sometimes don't take
    "create":    {"success_rate": 0.75, "duration": 1.5},   # creating indexes can fail
    "restore":   {"success_rate": 0.70, "duration": 2.0},   # schema restores are risky
    "terminate": {"success_rate": 0.85, "duration": 0.8},
    "update":    {"success_rate": 0.80, "duration": 1.0},
    "default":   {"success_rate": 0.90, "duration": 0.6},
}


def simulate_action(step: str) -> dict:
    """
    Simulates executing a single recovery step.
    Returns whether it succeeded, how long it took, and a result message.
    """
    # Figure out what kind of action this is from the step text
    step_lower = step.lower()
    action_type = "default"
    for keyword in ACTION_OUTCOMES:
        if keyword in step_lower:
            action_type = keyword
            break

    config = ACTION_OUTCOMES[action_type]

    # Simulate execution time
    time.sleep(config["duration"] * 0.1)  # scaled down so tests run fast

    # Determine success/failure probabilistically
    succeeded = random.random() < config["success_rate"]

    if succeeded:
        return {
            "step": step,
            "status": "success",
            "message": f"Completed successfully",
            "action_type": action_type
        }
    else:
        return {
            "step": step,
            "status": "failed",
            "message": f"Action failed — manual intervention may be required",
            "action_type": action_type
        }


# ── THE PROMPT ─────────────────────────────────────────────────────────────────
# Claude's role here is different — it's not making decisions.
# It's interpreting the execution results and writing a clear summary
# of what was done, what worked, what failed, and what the final status is.
# Think of it as the "executive summary writer" for the execution run.

EXECUTION_SYSTEM_PROMPT = """
You are the Execution Agent in an autonomous infrastructure operations system.

Recovery steps have already been executed by the system.
Your job is to interpret the execution results and determine the overall outcome.

You must respond with ONLY a JSON object. No explanation, no markdown, no extra text.

Response format:
{
  "actions_taken": ["description of step 1 outcome", "description of step 2 outcome"],
  "execution_status": "success" | "partial" | "failed",
  "execution_errors": ["error description if any"]
}

Rules:
- execution_status is "success" if ALL steps succeeded
- execution_status is "partial" if SOME steps succeeded and some failed
- execution_status is "failed" if the FIRST step failed or ALL steps failed
- actions_taken should summarize what each step did in plain language
- execution_errors should list only the steps that failed and why
- If no errors occurred, execution_errors should be an empty list []
""".strip()


def build_user_message(state: dict, step_results: list) -> str:
    """
    Passes the execution results to Claude for interpretation and summarization.
    """
    results_text = "\n".join(
        f"  Step {i+1}: [{r['status'].upper()}] {r['step']} → {r['message']}"
        for i, r in enumerate(step_results)
    )

    return f"""
Pipeline: {state["pipeline_name"]}
Failure type: {state["failure_type"]}
Root cause: {state["root_cause"]}

Execution results:
{results_text}

Summarize these results and return your JSON response.
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
            "actions_taken": ["Parse error — see raw logs"],
            "execution_status": "failed",
            "execution_errors": [f"Execution agent parse error: {response_text[:100]}"]
        }


def execution_agent(state: dict) -> dict:
    """
    The Execution Agent node function.

    This agent does TWO things (unlike the others which only call Claude):
    1. Simulate running each recovery step and collect results
    2. Call Claude to interpret and summarize those results

    Reads:  recovery_plan, approved (must be True to reach this node)
    Writes: actions_taken, execution_status, execution_errors
    """
    print(f"\n[Execution Agent] Starting recovery execution for: {state['pipeline_name']}")
    print(f"[Execution Agent] Plan has {len(state['recovery_plan'])} steps")

    # ── PHASE 1: Execute each step ─────────────────────────────────────────────
    step_results = []
    for i, step in enumerate(state["recovery_plan"]):
        print(f"\n[Execution Agent] Running step {i+1}: {step[:60]}...")
        result = simulate_action(step)
        step_results.append(result)
        status_icon = "✓" if result["status"] == "success" else "✗"
        print(f"[Execution Agent] {status_icon} {result['status'].upper()}: {result['message']}")

        # If a critical early step fails, stop executing
        # No point running step 4 if step 1 (the health check) failed
        if result["status"] == "failed" and i < 2:
            print(f"[Execution Agent] Critical step failed — halting execution")
            break

    # ── PHASE 2: Claude interprets the results ─────────────────────────────────
    print(f"\n[Execution Agent] Interpreting results with Claude...")
    user_message = build_user_message(state, step_results)

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=512,
        system=EXECUTION_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": user_message}
        ]
    )

    response_text = response.content[0].text
    print(f"[Execution Agent] Raw response: {response_text}")

    result = parse_claude_response(response_text)

    status_icon = "✓" if result["execution_status"] == "success" else "~" if result["execution_status"] == "partial" else "✗"
    print(f"\n[Execution Agent] {status_icon} Final status: {result['execution_status'].upper()}")
    if result.get("execution_errors"):
        for err in result["execution_errors"]:
            print(f"[Execution Agent]   Error: {err}")

    # Return ONLY the fields this agent owns
    # LangGraph merges this partial update into the full state - then it's passed to the next agent (likely the Human Approval Agent)
    # Give Audit Agent the actions taken, execution status, and execution errors
    return {
        "actions_taken":     result["actions_taken"],
        "execution_status":  result["execution_status"],
        "execution_errors":  result.get("execution_errors", []),
        "current_agent":     "execution_agent"
    }


# ── LOCAL TEST ─────────────────────────────────────────────────────────────────
# For testing, we use pipeline_crash with a SAFE plan (no service restarts)
# so Security would approve it. This simulates the approved execution path.

if __name__ == "__main__":
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from simulator.failure_sim import generate_failure

    # Simulate a pipeline_crash scenario that Security approved
    # Plan is read-only checks only — no destructive steps
    approved_state = {
        "failure_detected": True,
        "failure_type": "pipeline_crash",
        "failure_summary": "Pipeline failed to connect to payments_db after exhausting all 3 retry attempts.",
        "root_cause": "PostgreSQL server 'payments_db' on port 5432 is unreachable.",
        "affected_components": ["payments_db", "etl_payments_pipeline"],
        "diagnosis_confidence": "high",
        "recovery_plan": [
            "Step 1: Check PostgreSQL service status on payments_db",
            "Step 2: Verify network connectivity from ETL host to payments_db:5432",
            "Step 3: Review PostgreSQL logs for recent errors",
            "Step 4: Run health check on payments_db connection pool",
            "Step 5: Re-run etl_payments_pipeline and monitor connection",
        ],
        "estimated_risk": "low",
        "risk_level": "low",
        "approved": True,
        "approval_reason": "All steps are read-only checks and a pipeline re-run — safe to auto-execute.",
    }

    state = generate_failure("pipeline_crash")
    state.update(approved_state)

    print("=" * 50)
    print("Testing Execution Agent in isolation")
    print("=" * 50)

    result = execution_agent(state)
    print(f"\nFinal result: {json.dumps(result, indent=2)}")