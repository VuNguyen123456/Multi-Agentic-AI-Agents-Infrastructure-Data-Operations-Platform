import sys
import os
import json
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from simulator.failure_sim import generate_failure
from orchestrator.graph import graph


def run(scenario: str = None):
    """
    Runs the full multi-agent pipeline for a given failure scenario.

    Args:
        scenario: "schema_drift" | "latency_spike" | "pipeline_crash" | None (random)
    """
    print("\n" + "=" * 60)
    print("  MULTI-AGENT INFRASTRUCTURE RECOVERY SYSTEM")
    print("=" * 60)

    # Generate the initial state from the simulator
    initial_state = generate_failure(scenario)

    print(f"\n  Scenario : {scenario or 'random'}")
    print(f"  Pipeline : {initial_state['pipeline_name']}")
    print("=" * 60)

    # Run the full graph — this triggers the entire agent chain
    final_state = graph.invoke(initial_state)

    # ── FINAL SUMMARY ──────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  RUN COMPLETE")
    print("=" * 60)
    print(f"  Failure type : {final_state.get('failure_type')}")
    print(f"  Risk level   : {final_state.get('risk_level')}")
    print(f"  Approved     : {final_state.get('approved')}")
    print(f"  Exec status  : {final_state.get('execution_status', 'not executed')}")
    print(f"  Completed at : {final_state.get('completed_at')}")
    print("=" * 60)

    return final_state


if __name__ == "__main__":
    # Optionally pass a scenario name as a command line argument:
    #   python main.py schema_drift
    #   python main.py latency_spike
    #   python main.py pipeline_crash
    #   python main.py              ← picks one at random
    scenario = sys.argv[1] if len(sys.argv) > 1 else None
    run(scenario)