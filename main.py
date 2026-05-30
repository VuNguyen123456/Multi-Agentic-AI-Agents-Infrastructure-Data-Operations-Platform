import sys
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from simulator.failure_sim import generate_failure
from orchestrator.graph import graph


def run(scenario: str = None):
    print("\n" + "=" * 60)
    print("  MULTI-AGENT INFRASTRUCTURE RECOVERY SYSTEM")
    print("=" * 60)

    initial_state = generate_failure(scenario)
    print(f"\n  Scenario : {scenario or 'random'}")
    print(f"  Pipeline : {initial_state['pipeline_name']}")
    print("=" * 60)

    try:
        final_state = graph.invoke(initial_state)

        print("\n" + "=" * 60)
        print("  RUN COMPLETE")
        print("=" * 60)
        print(f"  Failure type : {final_state.get('failure_type')}")
        print(f"  Risk level   : {final_state.get('risk_level')}")
        print(f"  Approved     : {final_state.get('approved')}")
        print(f"  Exec status  : {final_state.get('execution_status', 'not executed')}")
        print(f"  Completed at : {final_state.get('completed_at')}")
        print("=" * 60)

    except Exception as e:
        print("\n" + "=" * 60)
        print("  GRAPH PAUSED — HUMAN APPROVAL REQUIRED")
        print("=" * 60)
        print(f"\n  The Security Agent flagged this plan as HIGH RISK.")
        print(f"\n  Run via the API server for full human-in-the-loop:")
        print(f"    uvicorn api.main:app --reload")
        print("=" * 60)


if __name__ == "__main__":
    scenario = sys.argv[1] if len(sys.argv) > 1 else None
    run(scenario)