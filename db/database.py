import psycopg2
import psycopg2.extras
import json
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

DB_CONFIG = {
    "host":     os.getenv("POSTGRES_HOST", "127.0.0.1"),
    "port":     int(os.getenv("POSTGRES_PORT", 5434)),
    "dbname":   os.getenv("POSTGRES_DB",   "infra_ops"),
    "user":     os.getenv("POSTGRES_USER", "admin"),
    "password": os.getenv("POSTGRES_PASSWORD", "password"),
}


def get_connection():
    """Returns a new Postgres connection. Caller is responsible for closing it."""
    return psycopg2.connect(**DB_CONFIG)


def save_incident(state: dict, audit_result: dict, thread_id: str = None) -> int:
    """
    Saves a completed incident run to the incidents table.

    Args:
        state:        The final AgentState after the full graph run
        audit_result: The parsed audit JSON from the Audit Agent
        thread_id:    The LangGraph thread_id if run via FastAPI (optional)

    Returns:
        The new incident row id
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO incidents (
                        thread_id,
                        pipeline_name,
                        failure_type,
                        risk_level,
                        approved,
                        human_approved,
                        execution_status,
                        outcome,
                        incident_summary,
                        timeline,
                        recommendations,
                        actions_taken,
                        execution_errors,
                        root_cause,
                        recovery_plan,
                        completed_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING id
                """, (
                    thread_id,
                    state.get("pipeline_name"),
                    state.get("failure_type"),
                    state.get("risk_level"),
                    state.get("approved"),
                    state.get("human_approved"),
                    state.get("execution_status"),
                    audit_result.get("outcome"),
                    audit_result.get("incident_summary"),
                    json.dumps(audit_result.get("timeline", [])),
                    json.dumps(audit_result.get("recommendations", [])),
                    json.dumps(state.get("actions_taken") or []),
                    json.dumps(state.get("execution_errors") or []),
                    state.get("root_cause"),
                    json.dumps(state.get("recovery_plan") or []),
                    state.get("completed_at"),
                ))
                row_id = cur.fetchone()[0]
                print(f"[Database] Incident saved → id: {row_id}")
                return row_id
    finally:
        conn.close()


def get_recent_incidents(limit: int = 20) -> list:
    """Fetches the most recent incidents for the dashboard."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM incident_summary LIMIT %s
            """, (limit,))
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_incident_by_id(incident_id: int) -> dict:
    """Fetches a single full incident record by id."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM incidents WHERE id = %s", (incident_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def get_stats() -> dict:
    """Returns aggregate stats for the Grafana dashboard."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    COUNT(*)                                            AS total,
                    COUNT(*) FILTER (WHERE outcome = 'resolved')       AS resolved,
                    COUNT(*) FILTER (WHERE outcome = 'requires_human') AS requires_human,
                    COUNT(*) FILTER (WHERE outcome = 'failed')         AS failed,
                    COUNT(*) FILTER (WHERE human_approved = true)      AS human_approved,
                    COUNT(*) FILTER (WHERE human_approved = false
                                    AND human_approved IS NOT NULL)    AS human_rejected
                FROM incidents
            """)
            return dict(cur.fetchone())
    finally:
        conn.close()


def _group_counts(cur, sql: str) -> dict:
    cur.execute(sql)
    return {row["label"]: int(row["count"]) for row in cur.fetchall()}


def get_incident_breakdowns() -> dict:
    """Grouped counts for dashboard bar charts (all time in Postgres)."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            return {
                "outcomes": _group_counts(cur, """
                    SELECT COALESCE(outcome, 'unknown') AS label, COUNT(*)::int AS count
                    FROM incidents GROUP BY 1 ORDER BY count DESC
                """),
                "failure_types": _group_counts(cur, """
                    SELECT COALESCE(failure_type, 'unknown') AS label, COUNT(*)::int AS count
                    FROM incidents GROUP BY 1 ORDER BY count DESC
                """),
                "approvals": _group_counts(cur, """
                    SELECT CASE
                        WHEN human_approved IS NULL THEN 'auto_approved'
                        WHEN human_approved THEN 'human_approved'
                        ELSE 'human_rejected'
                    END AS label, COUNT(*)::int AS count
                    FROM incidents GROUP BY 1 ORDER BY count DESC
                """),
            }
    finally:
        conn.close()


if __name__ == "__main__":
    # Quick connectivity test
    try:
        conn = get_connection()
        conn.close()
        print("[OK] Postgres connected successfully")
    except Exception as e:
        print(f"[FAIL] Postgres connection failed: {e}")