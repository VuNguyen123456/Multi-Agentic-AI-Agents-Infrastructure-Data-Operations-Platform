"""
azure/emit_failures.py

Emits realistic pipeline failure events to Azure Application Insights.
Run this once to seed App Insights with test data before testing ingest.

Usage:
    python azure/emit_failures.py
    python azure/emit_failures.py --scenario disk_full
"""
import sys
import os
import argparse
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from opencensus.ext.azure.log_exporter import AzureLogHandler
import logging

CONNECTION_STRING = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
if not CONNECTION_STRING:
    print("ERROR: APPLICATIONINSIGHTS_CONNECTION_STRING not set in .env")
    sys.exit(1)

# ── LOGGER SETUP ───────────────────────────────────────────────────────────────
logger = logging.getLogger("pipeline_emitter")
logger.setLevel(logging.DEBUG)
logger.addHandler(AzureLogHandler(connection_string=CONNECTION_STRING))


# ── FAILURE TEMPLATES ──────────────────────────────────────────────────────────
# Each template maps to a failure scenario.
# These get emitted as real log events to App Insights.

FAILURE_TEMPLATES = {
    "schema_drift": {
        "pipeline_name":  "etl_orders_pipeline",
        "failure_type":   "schema_drift",
        "error_rate":     1.0,
        "rows_processed": 0,
        "rows_expected":  5000,
        "latency_ms":     340,
        "log_lines": [
            "etl_orders_pipeline starting run",
            "connecting to source: postgres://orders_db",
            "schema validation failed: column 'customer_email' not found",
            "expected columns: ['id','customer_id','customer_email','amount','created_at']",
            "actual columns: ['id','customer_id','amount','created_at']",
            "pipeline aborted: schema mismatch on table 'orders'",
            "0 rows committed. run FAILED.",
        ]
    },
    "disk_full": {
        "pipeline_name":  "etl_analytics_pipeline",
        "failure_type":   "disk_full",
        "error_rate":     1.0,
        "rows_processed": 3400,
        "rows_expected":  15000,
        "latency_ms":     1200,
        "log_lines": [
            "etl_analytics_pipeline starting run",
            "connection established to analytics_db",
            "batch 1 committed successfully (500 rows)",
            "batch 2 committed successfully (500 rows)",
            "could not write to file 'pg_wal/000000010000001': No space left on device",
            "ERROR: could not extend file 'base/16384/2619': No space left on device",
            "HINT: Check free disk space",
            "database server disk is full — aborting all writes",
            "3400 rows committed before failure. run FAILED.",
        ]
    },
    "pipeline_crash": {
        "pipeline_name":  "etl_payments_pipeline",
        "failure_type":   "pipeline_crash",
        "error_rate":     1.0,
        "rows_processed": 0,
        "rows_expected":  12000,
        "latency_ms":     0,
        "log_lines": [
            "etl_payments_pipeline starting run",
            "connection refused: could not connect to server",
            "host: payments_db port: 5432",
            "retrying in 5s... (attempt 1/3)",
            "connection refused: could not connect to server",
            "retrying in 5s... (attempt 2/3)",
            "all retries exhausted. pipeline_crash.",
            "0 rows committed. run FAILED.",
        ]
    },
    "out_of_memory": {
        "pipeline_name":  "etl_reporting_pipeline",
        "failure_type":   "out_of_memory",
        "error_rate":     1.0,
        "rows_processed": 7800,
        "rows_expected":  50000,
        "latency_ms":     8200,
        "log_lines": [
            "etl_reporting_pipeline starting run",
            "loading dataset: reporting_db.fact_events",
            "memory usage: 1.2GB / 4.0GB",
            "memory usage: 3.6GB / 4.0GB — approaching limit",
            "memory usage: 3.9GB / 4.0GB — critical",
            "Killed (signal 9) — OOM killer terminated process",
            "process exited with code -9",
            "7800 rows committed before OOM kill. run FAILED.",
        ]
    },
}


def emit_failure(scenario: str):
    """Emits a pipeline failure event to Azure Application Insights."""
    if scenario not in FAILURE_TEMPLATES:
        print(f"Unknown scenario: {scenario}. Choose from: {list(FAILURE_TEMPLATES.keys())}")
        return

    template = FAILURE_TEMPLATES[scenario]
    pipeline = template["pipeline_name"]
    timestamp = datetime.utcnow().isoformat()

    print(f"\n[Emitter] Sending {scenario} failure for {pipeline} to App Insights...")

    # Emit each log line as a separate trace event
    for line in template["log_lines"]:
        level = logging.ERROR if "FAIL" in line or "error" in line.lower() or "refused" in line.lower() else logging.INFO
        logger.log(level, line, extra={
            "custom_dimensions": {
                "pipeline_name":  pipeline,
                "failure_type":   template["failure_type"],
                "error_rate":     str(template["error_rate"]),
                "rows_processed": str(template["rows_processed"]),
                "rows_expected":  str(template["rows_expected"]),
                "latency_ms":     str(template["latency_ms"]),
                "emitted_at":     timestamp,
                "source":         "pipeline_emitter",
            }
        })

    # Also emit a summary event
    logger.error(
        f"PIPELINE_FAILURE: {pipeline} | type={template['failure_type']} | "
        f"rows={template['rows_processed']}/{template['rows_expected']} | "
        f"error_rate={template['error_rate']}",
        extra={
            "custom_dimensions": {
                "pipeline_name":  pipeline,
                "failure_type":   template["failure_type"],
                "error_rate":     str(template["error_rate"]),
                "rows_processed": str(template["rows_processed"]),
                "rows_expected":  str(template["rows_expected"]),
                "latency_ms":     str(template["latency_ms"]),
                "emitted_at":     timestamp,
                "source":         "pipeline_emitter",
                "event_type":     "PIPELINE_FAILURE",
            }
        }
    )

    print(f"[Emitter] ✓ Emitted {len(template['log_lines']) + 1} events for {pipeline}")
    print(f"[Emitter] Allow 2-3 minutes for logs to appear in App Insights")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Emit pipeline failures to Azure App Insights")
    parser.add_argument("--scenario", default=None, help="Scenario to emit (default: all)")
    args = parser.parse_args()

    if args.scenario:
        emit_failure(args.scenario)
    else:
        print("[Emitter] Emitting all failure scenarios...")
        for scenario in FAILURE_TEMPLATES:
            emit_failure(scenario)
            time.sleep(1)

    print("\n[Emitter] Done. Check Azure Portal → App Insights → Logs in ~2 minutes")