"""
azure/ingest.py

Queries Azure Application Insights via REST API for recent pipeline failures
and returns them as AgentState — same format as failure_sim.py.

Uses API key auth (no Azure AD / service principal needed).
"""
import os
import sys
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

APP_ID  = os.getenv("APPLICATIONINSIGHTS_APP_ID")
API_KEY = os.getenv("APPLICATIONINSIGHTS_API_KEY")
BASE_URL = f"https://api.applicationinsights.io/v1/apps/{APP_ID}/query"


def query(kql: str) -> list:
    """Runs a KQL query against App Insights and returns rows."""
    response = requests.post(
        BASE_URL,
        headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
        json={"query": kql},
        timeout=30
    )
    response.raise_for_status()
    data   = response.json()
    tables = data.get("tables", [])
    if not tables:
        return []
    table = tables[0]
    cols  = [c["name"] for c in table["columns"]]
    return [dict(zip(cols, row)) for row in table["rows"]]


# ── KQL QUERIES ────────────────────────────────────────────────────────────────

KQL_LATEST_FAILURE = """
traces
| where timestamp > ago(2h)
| where customDimensions.event_type == "PIPELINE_FAILURE"
| extend
    pipeline_name  = tostring(customDimensions.pipeline_name),
    failure_type   = tostring(customDimensions.failure_type),
    error_rate     = todouble(customDimensions.error_rate),
    rows_processed = toint(customDimensions.rows_processed),
    rows_expected  = toint(customDimensions.rows_expected),
    latency_ms     = toint(customDimensions.latency_ms)
| order by timestamp desc
| take 1
| project pipeline_name, failure_type, error_rate, rows_processed, rows_expected, latency_ms
"""

KQL_LOG_LINES = """
traces
| where timestamp > ago(2h)
| where customDimensions.source == "pipeline_emitter"
| where tostring(customDimensions.pipeline_name) == "{pipeline_name}"
| where customDimensions.event_type != "PIPELINE_FAILURE"
| order by timestamp asc
| project message
| take 20
"""


def ingest_from_azure() -> dict:
    """
    Queries App Insights for the most recent pipeline failure.
    Returns an AgentState dict identical to generate_failure().
    """
    print("[Azure Ingest] Querying App Insights for recent pipeline failures...")

    if not APP_ID or not API_KEY:
        raise RuntimeError(
            "Missing APPLICATIONINSIGHTS_APP_ID or APPLICATIONINSIGHTS_API_KEY in .env"
        )

    # ── Query 1: Latest failure summary ───────────────────────────────────────
    rows = query(KQL_LATEST_FAILURE)
    if not rows:
        raise RuntimeError(
            "No PIPELINE_FAILURE events in the last 2 hours. "
            "Run: python azure/emit_failures.py to seed test data."
        )

    row            = rows[0]
    pipeline_name  = row.get("pipeline_name",  "unknown_pipeline")
    failure_type   = row.get("failure_type",   "pipeline_crash")
    error_rate     = float(row.get("error_rate",     1.0) or 1.0)
    rows_processed = int(row.get("rows_processed",   0)   or 0)
    rows_expected  = int(row.get("rows_expected",    0)   or 0)
    latency_ms     = int(row.get("latency_ms",       0)   or 0)

    print(f"[Azure Ingest] Found: {failure_type} on {pipeline_name}")

    # ── Query 2: Raw log lines ─────────────────────────────────────────────────
    log_rows = query(KQL_LOG_LINES.format(pipeline_name=pipeline_name))
    raw_logs = [
        f"[AZURE] {r['message']}" for r in log_rows if r.get("message")
    ]

    if not raw_logs:
        raw_logs = [f"[AZURE] Pipeline failure detected: {failure_type} on {pipeline_name}"]

    print(f"[Azure Ingest] Retrieved {len(raw_logs)} log lines")

    # ── Return AgentState-compatible dict ──────────────────────────────────────
    return {
        "pipeline_name": pipeline_name,
        "pipeline_metrics": {
            "latency_ms":     latency_ms,
            "rows_processed": rows_processed,
            "rows_expected":  rows_expected,
            "error_rate":     error_rate,
            "last_success":   (
                datetime.now(timezone.utc) - timedelta(hours=2)
            ).isoformat(),
            "source": "azure_application_insights",
        },
        "raw_logs":             raw_logs,
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


if __name__ == "__main__":
    try:
        state = ingest_from_azure()
        print(f"\n✓ Successfully ingested from Azure App Insights:")
        print(f"  Pipeline : {state['pipeline_name']}")
        print(f"  Metrics  : {state['pipeline_metrics']}")
        print(f"  Logs ({len(state['raw_logs'])} lines):")
        for line in state["raw_logs"]:
            print(f"    {line}")
    except Exception as e:
        print(f"\n✗ Ingest failed: {e}")