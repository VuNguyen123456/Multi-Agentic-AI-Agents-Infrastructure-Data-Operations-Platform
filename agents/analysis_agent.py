import json
import os
from pathlib import Path
from anthropic import Anthropic


def _load_environment() -> None:
    """
    Load env vars early so API clients can be initialized safely.
    """
    try:
        from dotenv import load_dotenv
        project_root = Path(__file__).resolve().parents[1]
        load_dotenv(project_root / ".env")
    except ImportError:
        # If python-dotenv isn't installed, rely on shell environment.
        pass


def _build_client() -> Anthropic:
    """
    Build Anthropic client after env vars are loaded.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing ANTHROPIC_API_KEY. Add it to .env or export it in your shell."
        )
    return Anthropic(api_key=api_key)


_load_environment()
client = _build_client()


# ── THE PROMPT ─────────────────────────────────────────────────────────────────
# The Analysis Agent picks up where Monitoring left off.
# Monitoring said WHAT failed. Analysis figures out WHY.
# It has more context than Monitoring — it reads the failure type as a hint
# and does deeper reasoning on the logs and metrics.

ANALYSIS_SYSTEM_PROMPT = """
You are the Analysis Agent in an autonomous infrastructure operations system.

The Monitoring Agent has already confirmed a failure occurred and classified its type.
Your job is to go deeper: read the logs and metrics carefully and find the ROOT CAUSE.

You must determine:
1. What specifically caused this failure? (the root cause)
2. Which components are affected?
3. How confident are you in this diagnosis?

You must respond with ONLY a JSON object. No explanation, no markdown, no extra text.

Response format:
{
  "root_cause": "specific technical explanation of why the failure occurred",
  "affected_components": ["component1", "component2"],
  "diagnosis_confidence": "high" | "medium" | "low"
}

Rules:
- root_cause must be specific and technical, not vague. Bad: "the pipeline failed". Good: "column customer_email was dropped from the orders table, causing schema validation to abort the run"
- affected_components should name the actual system components involved (tables, services, connections, etc.)
- diagnosis_confidence is "high" if the logs clearly show the cause, "medium" if you're inferring, "low" if you're guessing
- Do not invent information not present in the logs or metrics
- root_cause should be 1-2 sentences maximum
""".strip()

# Build the user message and call Claude so that it's effectively cached from user tongue to Claude's tongue

def build_user_message(state: dict) -> str:
    """
    Packages everything the Analysis Agent needs:
    - What monitoring already found (failure type + summary)
    - The raw pipeline data to reason over
    """
    metrics = state["pipeline_metrics"]
    logs = state["raw_logs"]

    return f"""
Pipeline name: {state["pipeline_name"]}
Failure type (from Monitoring Agent): {state["failure_type"]}
Monitoring summary: {state["failure_summary"]}

Metrics:
- Latency: {metrics.get("latency_ms", "unknown")} ms
- Rows processed: {metrics.get("rows_processed", "unknown")}
- Rows expected: {metrics.get("rows_expected", "unknown")}
- Error rate: {metrics.get("error_rate", "unknown")}
- Last successful run: {metrics.get("last_success", "unknown")}

Full logs:
{chr(10).join(logs)}

Analyze the root cause and return your JSON response.
""".strip()



def parse_claude_response(response_text: str) -> dict:
    """Same defensive parsing as monitoring — strip code fences if present."""
    try:
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        return json.loads(cleaned.strip())
    except json.JSONDecodeError:
        return {
            "root_cause": f"Analysis agent parse error: {response_text[:100]}",
            "affected_components": [],
            "diagnosis_confidence": "low"
        }


def analysis_agent(state: dict) -> dict:
    """
    The Analysis Agent node function.

    Reads: pipeline data + monitoring output (failure_type, failure_summary)
    Writes: root_cause, affected_components, diagnosis_confidence
    """
    print(f"\n[Analysis Agent] Investigating: {state['failure_type']} on {state['pipeline_name']}")

    user_message = build_user_message(state)

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=512,       # Analysis needs more tokens than monitoring
        system=ANALYSIS_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": user_message}
        ]
    )

    response_text = response.content[0].text
    print(f"[Analysis Agent] Raw response: {response_text}")

    result = parse_claude_response(response_text)

    print(f"[Analysis Agent] Root cause: {result['root_cause']}")
    print(f"[Analysis Agent] Affected: {result['affected_components']}")
    print(f"[Analysis Agent] Confidence: {result['diagnosis_confidence']}")

    # Return ONLY the fields this agent owns
    # LangGraph merges this partial update into the full state - then it's passed to the next agent (likely the Planning Agent)
    # Give Planning Agent the root cause, affected components, and diagnosis confidence
    return {
        "root_cause":             result["root_cause"],
        "affected_components":    result.get("affected_components", []),
        "diagnosis_confidence":   result.get("diagnosis_confidence", "low"),
        "current_agent":          "analysis_agent"
    }


# ── LOCAL TEST ─────────────────────────────────────────────────────────────────
# Simulates what happens when LangGraph passes state from Monitoring → Analysis.
# We manually build a state that looks like monitoring already ran.

if __name__ == "__main__":
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from simulator.failure_sim import generate_failure

    # Simulated monitoring outputs for each scenario
    # This is what state looks like AFTER monitoring_agent runs
    monitoring_outputs = {
        "schema_drift": {
            "failure_detected": True,
            "failure_type": "schema_drift",
            "failure_summary": "Pipeline aborted because the 'customer_email' column is missing from the orders table.",
        },
        "latency_spike": {
            "failure_detected": True,
            "failure_type": "latency_spike",
            "failure_summary": "Pipeline timed out after 45s, processing only 1200 of 5000 rows.",
        },
        "pipeline_crash": {
            "failure_detected": True,
            "failure_type": "pipeline_crash",
            "failure_summary": "Pipeline failed to connect to payments_db after exhausting all 3 retry attempts.",
        },
    }

    print("=" * 50)
    print("Testing Analysis Agent in isolation")
    print("=" * 50)

    for scenario in ["schema_drift", "latency_spike", "pipeline_crash"]:
        print(f"\n--- Scenario: {scenario} ---")

        # Start with the base simulated failure
        state = generate_failure(scenario)

        # Merge in what the monitoring agent would have written
        state.update(monitoring_outputs[scenario])

        result = analysis_agent(state)
        print(f"Result: {json.dumps(result, indent=2)}")
        print()