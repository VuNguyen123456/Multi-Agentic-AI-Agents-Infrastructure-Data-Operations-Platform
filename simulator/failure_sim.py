# The mock and the real AWS version are structurally the same thing. 
# The only difference is where the data comes from

import random
from datetime import datetime, timedelta

# ── SCENARIO DEFINITIONS ───────────────────────────────────────────────────────
# Each scenario is a complete snapshot of a "broken" pipeline.
# The Monitoring Agent will read this and decide what's wrong.

# Scenario 1 — Schema drift (etl_orders_pipeline)
# Imagine a team running a nightly ETL job that pulls orders from a Postgres database and loads them into a data warehouse. 
# One day, a backend developer drops the customer_email column from the orders table — maybe they renamed it, maybe they moved it elsewhere. Nobody told the data team. 
# The ETL job starts, tries to read customer_email, it's gone, the schema validator crashes immediately. Zero rows make it to the warehouse. 
# Finance notices in the morning that yesterday's order report is empty. 
# In real companies this happens constantly,schema changes without cross-team communication are one of the top causes of data pipeline failures.

# Scenario 2 — Latency spike (etl_inventory_pipeline)
# The inventory pipeline runs fine but keeps getting slower and slower with each batch.    
# Batch 1 takes 9 seconds, batch 2 takes 12, batch 3 takes 24 — then it hits the timeout and dies. Only 1,200 of 5,000 rows made it. 
# The real-world cause of this pattern is almost always a database under heavy load — maybe another team ran a massive query at the same time, maybe an index is missing, maybe the database server is memory-starved. 
# The pipeline itself is fine; the problem is somewhere upstream. This is tricky because the logs show the pipeline failing but the actual root cause is an overloaded database server.

# Scenario 3 — Pipeline crash (etl_payments_pipeline)
# The payments database is simply not reachable. Connection refused, three retries, all fail, nothing runs. 
# This is the bluntest failure: the infrastructure itself is down. 
# Real causes include a crashed Docker container, a misconfigured firewall rule after a deployment, a database server that ran out of disk space and stopped accepting connections, or a network partition between two services. 
# Payments data not flowing is a P0 incident at any company — every minute it's down is money not being recorded.

SCENARIOS = {
    "schema_drift": {
        "pipeline_name": "etl_orders_pipeline",
        "pipeline_metrics": {
            "latency_ms": 340,
            "rows_processed": 0,
            "rows_expected": 5000,
            "error_rate": 1.0,
            "last_success": (datetime.now() - timedelta(hours=3)).isoformat(),
        },
        "raw_logs": [
            "[INFO]  2024-01-15 09:00:01 etl_orders_pipeline starting run #4821",
            "[INFO]  2024-01-15 09:00:02 connecting to source: postgres://orders_db",
            "[INFO]  2024-01-15 09:00:02 connection established",
            "[INFO]  2024-01-15 09:00:03 fetching batch 1 of 10 (500 rows)",
            "[ERROR] 2024-01-15 09:00:03 schema validation failed: column 'customer_email' not found",
            "[ERROR] 2024-01-15 09:00:03 expected columns: ['id','customer_id','customer_email','amount','created_at']",
            "[ERROR] 2024-01-15 09:00:03 actual columns:   ['id','customer_id','amount','created_at']",
            "[ERROR] 2024-01-15 09:00:04 pipeline aborted: schema mismatch on table 'orders'",
            "[INFO]  2024-01-15 09:00:04 rolled back transaction",
            "[ERROR] 2024-01-15 09:00:04 0 rows committed. run FAILED.",
        ],
    },

    "latency_spike": {
        "pipeline_name": "etl_inventory_pipeline",
        "pipeline_metrics": {
            "latency_ms": 47800,
            "rows_processed": 1200,
            "rows_expected": 5000,
            "error_rate": 0.02,
            "last_success": (datetime.now() - timedelta(minutes=90)).isoformat(),
        },
        "raw_logs": [
            "[INFO]  2024-01-15 10:15:00 etl_inventory_pipeline starting run #2201",
            "[INFO]  2024-01-15 10:15:01 connecting to source: postgres://inventory_db",
            "[WARN]  2024-01-15 10:15:04 connection took 3100ms (threshold: 500ms)",
            "[INFO]  2024-01-15 10:15:04 fetching batch 1 of 10 (500 rows)",
            "[WARN]  2024-01-15 10:15:14 batch 1 took 9800ms to process (threshold: 2000ms)",
            "[INFO]  2024-01-15 10:15:14 fetching batch 2 of 10 (500 rows)",
            "[WARN]  2024-01-15 10:15:26 batch 2 took 12200ms to process (threshold: 2000ms)",
            "[INFO]  2024-01-15 10:15:26 fetching batch 3 of 10 (500 rows)",
            "[WARN]  2024-01-15 10:15:51 batch 3 took 24900ms to process (threshold: 2000ms)",
            "[ERROR] 2024-01-15 10:15:51 pipeline timeout exceeded (45000ms). aborting.",
            "[INFO]  2024-01-15 10:15:51 partial commit: 1200 rows saved before timeout",
        ],
    },

    "pipeline_crash": {
        "pipeline_name": "etl_payments_pipeline",
        "pipeline_metrics": {
            "latency_ms": 0,
            "rows_processed": 0,
            "rows_expected": 12000,
            "error_rate": 1.0,
            "last_success": (datetime.now() - timedelta(hours=6)).isoformat(),
        },
        "raw_logs": [
            "[INFO]  2024-01-15 08:00:00 etl_payments_pipeline starting run #9910",
            "[INFO]  2024-01-15 08:00:01 connecting to source: postgres://payments_db",
            "[ERROR] 2024-01-15 08:00:01 connection refused: could not connect to server",
            "[ERROR] 2024-01-15 08:00:01 host: payments_db port: 5432",
            "[INFO]  2024-01-15 08:00:01 retrying in 5s... (attempt 1/3)",
            "[ERROR] 2024-01-15 08:00:06 connection refused: could not connect to server",
            "[INFO]  2024-01-15 08:00:06 retrying in 5s... (attempt 2/3)",
            "[ERROR] 2024-01-15 08:00:11 connection refused: could not connect to server",
            "[FATAL] 2024-01-15 08:00:11 all retries exhausted. pipeline_crash.",
            "[ERROR] 2024-01-15 08:00:11 0 rows committed. run FAILED.",
        ],
    },
}


def generate_failure(scenario: str = None) -> dict:
    """
    Returns a simulated pipeline failure as initial LangGraph state.

    Args:
        scenario: "schema_drift" | "latency_spike" | "pipeline_crash"
                  Pass None to pick one at random.

    Returns:
        A dict that seeds AgentState at the start of the graph run.
    """
    if scenario is None:
        scenario = random.choice(list(SCENARIOS.keys()))

    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: '{scenario}'. Choose from {list(SCENARIOS.keys())}")

    data = SCENARIOS[scenario]

    # Return the initial state — only pipeline input fields are populated.
    # All agent output fields start as None (LangGraph handles missing keys fine).
    return {
        "pipeline_name":     data["pipeline_name"],
        "pipeline_metrics":  data["pipeline_metrics"],
        "raw_logs":          data["raw_logs"],
        "failure_detected":  False,   # Monitoring Agent will set this
        "failure_type":      None,
        "failure_summary":   None,
        "root_cause":        None,
        "affected_components": None,
        "diagnosis_confidence": None,
        "recovery_plan":     None,
        "estimated_risk":    None,
        "risk_level":        None,
        "approved":          None,
        "approval_reason":   None,
        "human_approved":    None,
        "human_notes":       None,
        "actions_taken":     None,
        "execution_status":  None,
        "execution_errors":  None,
        "audit_log":         None,
        "completed_at":      None,
        "current_agent":     None,
        "error_message":     None,
    }


if __name__ == "__main__":
    # Quick sanity check — run this file directly to see what state looks like
    import json
    print("=== Simulated failure scenario ===\n")
    state = generate_failure("schema_drift")
    print(f"Pipeline:  {state['pipeline_name']}")
    print(f"Metrics:   {json.dumps(state['pipeline_metrics'], indent=2)}")
    print(f"\nLogs:")
    for line in state["raw_logs"]:
        print(f"  {line}")