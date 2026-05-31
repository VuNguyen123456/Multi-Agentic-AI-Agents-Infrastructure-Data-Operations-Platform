import random
from datetime import datetime, timedelta

# ── SCENARIO DEFINITIONS ───────────────────────────────────────────────────────
# Each scenario mirrors a real production failure pattern.
# The Monitoring Agent reads these and decides what went wrong.
# In production, this data would come from CloudWatch, Prometheus, or Datadog.

SCENARIOS = {

    # ── 1. SCHEMA DRIFT ────────────────────────────────────────────────────────
    # A backend dev drops a column without telling the data team.
    # Schema validator catches it immediately. Zero rows committed.
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

    # ── 2. LATENCY SPIKE ───────────────────────────────────────────────────────
    # Pipeline runs but degrades progressively — missing index or DB contention.
    # Partial commit: 1,200 of 5,000 rows saved before timeout.
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

    # ── 3. PIPELINE CRASH ──────────────────────────────────────────────────────
    # Source database completely unreachable — connection refused on all retries.
    # Could be a crashed container, firewall change, or network partition.
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

    # ── 4. DISK FULL ───────────────────────────────────────────────────────────
    # DB server runs out of disk space mid-run. PostgreSQL stops accepting writes.
    # Unlike pipeline_crash, the DB is reachable — it just can't write anything.
    # Must clear disk before any re-run will succeed.
    "disk_full": {
        "pipeline_name": "etl_analytics_pipeline",
        "pipeline_metrics": {
            "latency_ms": 1200,
            "rows_processed": 3400,
            "rows_expected": 15000,
            "error_rate": 1.0,
            "last_success": (datetime.now() - timedelta(hours=2)).isoformat(),
        },
        "raw_logs": [
            "[INFO]  2024-01-15 11:00:00 etl_analytics_pipeline starting run #1102",
            "[INFO]  2024-01-15 11:00:01 connecting to source: postgres://analytics_db",
            "[INFO]  2024-01-15 11:00:01 connection established",
            "[INFO]  2024-01-15 11:00:02 fetching batch 1 of 30 (500 rows)",
            "[INFO]  2024-01-15 11:00:03 batch 1 committed successfully (500 rows)",
            "[INFO]  2024-01-15 11:00:04 fetching batch 2 of 30 (500 rows)",
            "[INFO]  2024-01-15 11:00:05 batch 2 committed successfully (500 rows)",
            "[INFO]  2024-01-15 11:00:06 fetching batch 3 of 30 (500 rows)",
            "[ERROR] 2024-01-15 11:00:07 could not write to file 'pg_wal/000000010000001': No space left on device",
            "[ERROR] 2024-01-15 11:00:07 ERROR: could not extend file 'base/16384/2619': No space left on device",
            "[ERROR] 2024-01-15 11:00:07 HINT: Check free disk space",
            "[FATAL] 2024-01-15 11:00:07 database server disk is full — aborting all writes",
            "[ERROR] 2024-01-15 11:00:08 rolling back transaction for batch 3",
            "[ERROR] 2024-01-15 11:00:08 pipeline aborted: storage failure on analytics_db",
            "[ERROR] 2024-01-15 11:00:08 3400 rows committed before failure. run FAILED.",
        ],
    },

    # ── 5. OUT OF MEMORY ───────────────────────────────────────────────────────
    # The pipeline worker process is killed by the OS OOM killer.
    # Happens when processing large datasets without memory limits set.
    # Common in Spark jobs, pandas-heavy ETL, or misconfigured containers.
    "out_of_memory": {
        "pipeline_name": "etl_reporting_pipeline",
        "pipeline_metrics": {
            "latency_ms": 8200,
            "rows_processed": 7800,
            "rows_expected": 50000,
            "error_rate": 1.0,
            "last_success": (datetime.now() - timedelta(hours=4)).isoformat(),
        },
        "raw_logs": [
            "[INFO]  2024-01-15 07:00:00 etl_reporting_pipeline starting run #331",
            "[INFO]  2024-01-15 07:00:01 loading dataset: reporting_db.fact_events (50000 rows expected)",
            "[INFO]  2024-01-15 07:00:02 memory usage: 1.2GB / 4.0GB",
            "[INFO]  2024-01-15 07:00:05 processing batch 1 (5000 rows) — applying transformations",
            "[INFO]  2024-01-15 07:00:08 memory usage: 2.8GB / 4.0GB",
            "[WARN]  2024-01-15 07:00:09 memory usage: 3.6GB / 4.0GB — approaching limit",
            "[INFO]  2024-01-15 07:00:11 processing batch 2 (5000 rows)",
            "[WARN]  2024-01-15 07:00:12 memory usage: 3.9GB / 4.0GB — critical",
            "[FATAL] 2024-01-15 07:00:13 Killed (signal 9) — OOM killer terminated process",
            "[ERROR] 2024-01-15 07:00:13 process exited with code -9",
            "[ERROR] 2024-01-15 07:00:13 7800 rows committed before OOM kill. run FAILED.",
        ],
    },

    # ── 6. DEADLOCK ────────────────────────────────────────────────────────────
    # Two transactions block each other, PostgreSQL kills one to resolve it.
    # Common when multiple pipelines write to the same tables concurrently.
    "deadlock": {
        "pipeline_name": "etl_user_events_pipeline",
        "pipeline_metrics": {
            "latency_ms": 4500,
            "rows_processed": 2100,
            "rows_expected": 8000,
            "error_rate": 0.35,
            "last_success": (datetime.now() - timedelta(minutes=45)).isoformat(),
        },
        "raw_logs": [
            "[INFO]  2024-01-15 14:00:00 etl_user_events_pipeline starting run #7823",
            "[INFO]  2024-01-15 14:00:01 connecting to source: postgres://events_db",
            "[INFO]  2024-01-15 14:00:01 connection established",
            "[INFO]  2024-01-15 14:00:02 fetching batch 1 of 16 (500 rows)",
            "[INFO]  2024-01-15 14:00:03 batch 1 committed (500 rows)",
            "[INFO]  2024-01-15 14:00:04 fetching batch 2 of 16 (500 rows)",
            "[INFO]  2024-01-15 14:00:05 batch 2 committed (500 rows)",
            "[INFO]  2024-01-15 14:00:06 fetching batch 3 of 16 (500 rows)",
            "[ERROR] 2024-01-15 14:00:09 ERROR: deadlock detected",
            "[ERROR] 2024-01-15 14:00:09 DETAIL: Process 4821 waits for ShareLock on transaction 9043",
            "[ERROR] 2024-01-15 14:00:09 DETAIL: Process 4820 waits for ShareLock on transaction 9041",
            "[ERROR] 2024-01-15 14:00:09 HINT: See server log for query details",
            "[ERROR] 2024-01-15 14:00:09 transaction aborted due to deadlock — batch 3 rolled back",
            "[INFO]  2024-01-15 14:00:09 retrying batch 3 (attempt 1/3)",
            "[ERROR] 2024-01-15 14:00:14 deadlock detected again on retry",
            "[FATAL] 2024-01-15 14:00:14 max retries exceeded. pipeline aborted.",
            "[ERROR] 2024-01-15 14:00:14 2100 rows committed before deadlock. run FAILED.",
        ],
    },

    # ── 7. REPLICATION LAG ─────────────────────────────────────────────────────
    # Read replica falls behind the primary. Pipeline reads stale data.
    # Common when primary has heavy write load or replica has resource constraints.
    "replication_lag": {
        "pipeline_name": "etl_customer_pipeline",
        "pipeline_metrics": {
            "latency_ms": 12400,
            "rows_processed": 4200,
            "rows_expected": 4200,
            "error_rate": 0.0,
            "last_success": (datetime.now() - timedelta(minutes=30)).isoformat(),
        },
        "raw_logs": [
            "[INFO]  2024-01-15 13:00:00 etl_customer_pipeline starting run #5541",
            "[INFO]  2024-01-15 13:00:01 connecting to read replica: postgres://customers_db_replica",
            "[INFO]  2024-01-15 13:00:01 connection established",
            "[WARN]  2024-01-15 13:00:02 replication lag detected: 00:04:32 behind primary",
            "[WARN]  2024-01-15 13:00:02 threshold: 00:01:00 — data may be stale",
            "[INFO]  2024-01-15 13:00:03 fetching batch 1 of 9 (500 rows)",
            "[WARN]  2024-01-15 13:00:04 replication lag increased: 00:06:15 behind primary",
            "[INFO]  2024-01-15 13:00:05 batch 1 committed (500 rows)",
            "[WARN]  2024-01-15 13:00:06 replication lag: 00:08:47 — exceeds critical threshold (00:05:00)",
            "[ERROR] 2024-01-15 13:00:06 data freshness SLA violated: replica is 8m47s behind",
            "[ERROR] 2024-01-15 13:00:06 downstream reports will contain stale customer records",
            "[FATAL] 2024-01-15 13:00:07 pipeline aborted: replication lag exceeds SLA threshold",
            "[ERROR] 2024-01-15 13:00:07 4200 rows written but data integrity compromised. run FAILED.",
        ],
    },

    # ── 8. DATA QUALITY FAILURE ────────────────────────────────────────────────
    # Pipeline runs fine technically but the source data is corrupt.
    # Null values in required fields, duplicates, or out-of-range values.
    # Common when upstream teams change how they generate data without notice.
    "data_quality": {
        "pipeline_name": "etl_transactions_pipeline",
        "pipeline_metrics": {
            "latency_ms": 2100,
            "rows_processed": 890,
            "rows_expected": 6000,
            "error_rate": 0.85,
            "last_success": (datetime.now() - timedelta(hours=1)).isoformat(),
        },
        "raw_logs": [
            "[INFO]  2024-01-15 12:00:00 etl_transactions_pipeline starting run #3302",
            "[INFO]  2024-01-15 12:00:01 connecting to source: postgres://transactions_db",
            "[INFO]  2024-01-15 12:00:01 connection established",
            "[INFO]  2024-01-15 12:00:02 fetching batch 1 of 12 (500 rows)",
            "[WARN]  2024-01-15 12:00:03 data quality check failed: 47 rows have NULL transaction_amount",
            "[WARN]  2024-01-15 12:00:03 data quality check failed: 23 rows have duplicate transaction_id",
            "[WARN]  2024-01-15 12:00:03 data quality check failed: 12 rows have negative amount values",
            "[INFO]  2024-01-15 12:00:03 quarantined 82 invalid rows. committed 418 valid rows.",
            "[INFO]  2024-01-15 12:00:04 fetching batch 2 of 12 (500 rows)",
            "[WARN]  2024-01-15 12:00:05 data quality check failed: 198 rows have NULL transaction_amount",
            "[ERROR] 2024-01-15 12:00:05 error rate 39.6% exceeds threshold (10%) — batch rejected",
            "[ERROR] 2024-01-15 12:00:05 data quality degradation detected across multiple batches",
            "[FATAL] 2024-01-15 12:00:06 pipeline aborted: source data quality below acceptable threshold",
            "[ERROR] 2024-01-15 12:00:06 890 valid rows committed. 5110 rows rejected or not processed.",
        ],
    },
}


def generate_failure(scenario: str = None) -> dict:
    """
    Returns a simulated pipeline failure as initial LangGraph state.

    Args:
        scenario: any key from SCENARIOS, or None to pick at random.

    Returns:
        A dict that seeds AgentState at the start of the graph run.
    """
    if scenario is None:
        scenario = random.choice(list(SCENARIOS.keys()))

    if scenario not in SCENARIOS:
        raise ValueError(
            f"Unknown scenario: '{scenario}'. "
            f"Choose from: {list(SCENARIOS.keys())}"
        )

    data = SCENARIOS[scenario]

    return {
        "input_scenario":       scenario,
        "pipeline_name":        data["pipeline_name"],
        "pipeline_metrics":     data["pipeline_metrics"],
        "raw_logs":             data["raw_logs"],
        "failure_detected":     False,
        "failure_type":         None,
        "failure_summary":      None,
        "root_cause":           None,
        "affected_components":  None,
        "diagnosis_confidence": None,
        "recovery_plan":        None,
        "estimated_risk":       None,
        "risk_level":           None,
        "approved":             None,
        "approval_reason":      None,
        "human_approved":       None,
        "human_notes":          None,
        "actions_taken":        None,
        "execution_status":     None,
        "execution_errors":     None,
        "audit_log":            None,
        "completed_at":         None,
        "current_agent":        None,
        "error_message":        None,
    }


def list_scenarios() -> list:
    """Returns all available scenario names."""
    return list(SCENARIOS.keys())


if __name__ == "__main__":
    import json
    print(f"Available scenarios: {list_scenarios()}\n")
    print("=== Sample: disk_full ===\n")
    state = generate_failure("disk_full")
    print(f"Pipeline : {state['pipeline_name']}")
    print(f"Metrics  : {json.dumps(state['pipeline_metrics'], indent=2)}")
    print(f"\nLogs:")
    for line in state["raw_logs"]:
        print(f"  {line}")