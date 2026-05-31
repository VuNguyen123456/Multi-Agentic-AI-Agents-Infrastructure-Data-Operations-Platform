-- Run this once to set up the database.
-- From your project root:
--   docker exec -i agenticaiproject-postgres-1 psql -U admin -d infra_ops < db/schema.sql

CREATE TABLE IF NOT EXISTS incidents (
    id              SERIAL PRIMARY KEY,
    thread_id       VARCHAR(64),
    pipeline_name   VARCHAR(128)    NOT NULL,
    failure_type    VARCHAR(64)     NOT NULL,
    risk_level      VARCHAR(16),
    approved        BOOLEAN,
    human_approved  BOOLEAN,
    execution_status VARCHAR(32),
    outcome         VARCHAR(32),
    incident_summary TEXT,
    timeline        JSONB,
    recommendations JSONB,
    actions_taken   JSONB,
    execution_errors JSONB,
    root_cause      TEXT,
    recovery_plan   JSONB,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_incidents_pipeline   ON incidents (pipeline_name);
CREATE INDEX IF NOT EXISTS idx_incidents_outcome    ON incidents (outcome);
CREATE INDEX IF NOT EXISTS idx_incidents_created_at ON incidents (created_at DESC);

-- View for quick incident history queries
CREATE OR REPLACE VIEW incident_summary AS
    SELECT
        id,
        thread_id,
        pipeline_name,
        failure_type,
        risk_level,
        approved,
        human_approved,
        execution_status,
        outcome,
        completed_at,
        created_at
    FROM incidents
    ORDER BY created_at DESC;