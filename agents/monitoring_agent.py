import json
import os
from pathlib import Path
from anthropic import Anthropic

# Import the shared state type for type hints
# (when you wire this into your project, this import works as-is)
# from state import AgentState

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
# This is the brain of the Monitoring Agent.
# We give Claude a clear role, strict output format, and the raw pipeline data.
# Nothing else — no analysis, no planning. Just: is something wrong, and what?

MONITORING_SYSTEM_PROMPT = """
You are the Monitoring Agent in an autonomous infrastructure operations system.

Your ONLY job is to look at pipeline metrics and logs and decide:
1. Did a failure occur?
2. If yes — what TYPE of failure is it?
3. Write a one-line human-readable summary.

Failure types you must classify into (pick exactly one):
- schema_drift     → columns missing, type mismatches, unexpected schema changes
- latency_spike    → pipeline ran but was unusually slow or timed out
- pipeline_crash   → pipeline could not start or connect, fatal errors, retries exhausted

You must respond with ONLY a JSON object. No explanation, no markdown, no extra text.

Response format:
{
  "failure_detected": true or false,
  "failure_type": "schema_drift" | "latency_spike" | "pipeline_crash" | null,
  "failure_summary": "one sentence describing what happened" | null
}

Rules:
- If no failure is detected, set failure_type and failure_summary to null
- failure_summary must be one sentence, under 20 words
- Do not invent information not present in the logs or metrics
""".strip()

# Build the user message and call Claude so that it's effectively cached from user tongue to Claude's tongue

def build_user_message(state: dict) -> str:
    """
    Packages the pipeline data from state into a clear message for Claude.
    We format it so Claude can read it like a real ops engineer would.
    """
    metrics = state["pipeline_metrics"]
    logs = state["raw_logs"]

    return f"""
Pipeline name: {state["pipeline_name"]}

Metrics:
- Latency: {metrics.get("latency_ms", "unknown")} ms
- Rows processed: {metrics.get("rows_processed", "unknown")}
- Rows expected: {metrics.get("rows_expected", "unknown")}
- Error rate: {metrics.get("error_rate", "unknown")}
- Last successful run: {metrics.get("last_success", "unknown")}

Recent logs:
{chr(10).join(logs)}

Analyze the above and return your JSON response.
""".strip()

# Parse the JSON Claude returned so it's human readable

def parse_claude_response(response_text: str) -> dict:
    try:
        # Strip markdown code fences if Claude includes them
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]  # get content between fences
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]          # strip the word "json"
        return json.loads(cleaned.strip())
    except json.JSONDecodeError:
        return {
            "failure_detected": False,
            "failure_type": None,
            "failure_summary": f"Monitoring agent parse error: {response_text[:100]}"
        }


# The Monitoring Agent node function, call and use the 2 functions above to build the user message and parse the response

def monitoring_agent(state: dict) -> dict:
    """
    The Monitoring Agent node function.

    LangGraph calls this with the full state dict.
    We read what we need, call Claude, and return ONLY the fields we own.

    Returns a partial state update — LangGraph merges this back automatically.
    """
    print(f"\n[Monitoring Agent] Analyzing pipeline: {state['pipeline_name']}")

    # Build the message Claude will read
    user_message = build_user_message(state)

    # Call Claude
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=256,        # Monitoring output is small — no need for more
        system=MONITORING_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": user_message}
        ]
    )

    response_text = response.content[0].text
    print(f"[Monitoring Agent] Raw response: {response_text}")

    # Parse the JSON Claude returned
    result = parse_claude_response(response_text)

    # Log what we found
    if result["failure_detected"]:
        print(f"[Monitoring Agent] ✗ Failure detected: {result['failure_type']}")
        print(f"[Monitoring Agent] Summary: {result['failure_summary']}")
    else:
        print(f"[Monitoring Agent] ✓ No failure detected")

    # Return ONLY the fields this agent owns
    # LangGraph merges this partial update into the full state - then it's passed to the next agent (likely the Analysis Agent)
    # Give Analysis Agent the failure detected, failure type, and failure summary
    return {
        "failure_detected": result["failure_detected"],
        "failure_type":     result.get("failure_type"),
        "failure_summary":  result.get("failure_summary"),
        "current_agent":    "monitoring_agent"
    }


# ── ROUTER FUNCTION ────────────────────────────────────────────────────────────
# This lives here because it's tightly coupled to monitoring's output.
# The LangGraph graph calls this after monitoring_agent runs to decide
# what node to go to next.

def route_after_monitoring(state: dict) -> str:
    """
    Conditional edge router — runs after the Monitoring Agent.

    Returns the name of the next node to run.
    LangGraph uses this string to look up the next node in the graph.
    """
    if state["failure_detected"]:
        print(f"[Router] Failure detected → routing to analysis_agent")
        return "analysis_agent"
    else:
        print(f"[Router] No failure → routing to END")
        return "END"


# ── LOCAL TEST ─────────────────────────────────────────────────────────────────
# Run this file directly to test the agent in isolation
# before wiring it into the full graph.
# Usage: python monitoring_agent.py

if __name__ == "__main__":
    import sys

    # Pull in the simulator
    # Adjust path if running from project root vs agents/ directory
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from simulator.failure_sim import generate_failure

    print("=" * 50)
    print("Testing Monitoring Agent in isolation")
    print("=" * 50)

    # Test each scenario
    for scenario in ["schema_drift", "latency_spike", "pipeline_crash"]:
        print(f"\n--- Scenario: {scenario} ---")
        state = generate_failure(scenario)
        result = monitoring_agent(state)
        print(f"Result: {json.dumps(result, indent=2)}")
        print()