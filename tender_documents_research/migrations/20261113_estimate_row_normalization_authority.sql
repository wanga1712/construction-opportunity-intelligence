-- Durable authority for full estimate-row taxonomy normalization.
-- Apply through the approved document_intelligence DDL route.

CREATE TABLE IF NOT EXISTS estimate_row_normalization_runs (
    id BIGSERIAL PRIMARY KEY,
    normalizer_version TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'RUNNING'
        CHECK (status IN ('RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED')),
    run_kind TEXT NOT NULL DEFAULT 'LIVE_RUN',
    proof_source TEXT NOT NULL DEFAULT 'LIVE_RUN',
    plan_sha256 TEXT,
    procurement_count INTEGER NOT NULL DEFAULT 0 CHECK (procurement_count >= 0),
    row_count_expected BIGINT NOT NULL DEFAULT 0 CHECK (row_count_expected >= 0),
    row_count_examined BIGINT NOT NULL DEFAULT 0 CHECK (row_count_examined >= 0),
    matched_rows BIGINT NOT NULL DEFAULT 0 CHECK (matched_rows >= 0),
    unmatched_rows BIGINT NOT NULL DEFAULT 0 CHECK (unmatched_rows >= 0),
    updated_rows BIGINT NOT NULL DEFAULT 0 CHECK (updated_rows >= 0),
    error_count INTEGER NOT NULL DEFAULT 0 CHECK (error_count >= 0),
    input_row_count BIGINT NOT NULL DEFAULT 0 CHECK (input_row_count >= 0),
    input_max_row_id BIGINT,
    input_rows_sha256 VARCHAR(64),
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_estimate_normalization_runs_version
    ON estimate_row_normalization_runs(normalizer_version, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_estimate_normalization_runs_status
    ON estimate_row_normalization_runs(status, started_at DESC);

CREATE TABLE IF NOT EXISTS estimate_row_normalization_procurements (
    run_id BIGINT NOT NULL
        REFERENCES estimate_row_normalization_runs(id) ON DELETE CASCADE,
    procurement_id BIGINT NOT NULL,
    normalizer_version TEXT NOT NULL,
    rows_expected BIGINT NOT NULL DEFAULT 0 CHECK (rows_expected >= 0),
    rows_examined BIGINT NOT NULL DEFAULT 0 CHECK (rows_examined >= 0),
    rows_matched BIGINT NOT NULL DEFAULT 0 CHECK (rows_matched >= 0),
    rows_unmatched BIGINT NOT NULL DEFAULT 0 CHECK (rows_unmatched >= 0),
    rows_updated BIGINT NOT NULL DEFAULT 0 CHECK (rows_updated >= 0),
    coverage_complete BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'PARTIAL'
        CHECK (status IN (
            'NOT_ATTEMPTED', 'DRY_RUN', 'PARTIAL', 'COMPLETED',
            'FAILED', 'STALE'
        )),
    input_row_count BIGINT NOT NULL DEFAULT 0 CHECK (input_row_count >= 0),
    input_max_row_id BIGINT,
    input_rows_sha256 VARCHAR(64),
    proof_source TEXT NOT NULL DEFAULT 'LIVE_RUN',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, procurement_id),
    CHECK (coverage_complete = (rows_expected = rows_examined))
);

CREATE INDEX IF NOT EXISTS idx_estimate_normalization_coverage_pid
    ON estimate_row_normalization_procurements(
        procurement_id, normalizer_version, updated_at DESC
    );
CREATE INDEX IF NOT EXISTS idx_estimate_normalization_coverage_status
    ON estimate_row_normalization_procurements(
        normalizer_version, status, procurement_id
    );

GRANT SELECT ON TABLE estimate_row_normalization_runs TO crm_app;
GRANT SELECT ON TABLE estimate_row_normalization_procurements TO crm_app;
GRANT SELECT, INSERT, UPDATE ON TABLE estimate_row_normalization_runs TO doc_worker;
GRANT SELECT, INSERT, UPDATE ON TABLE estimate_row_normalization_procurements TO doc_worker;
GRANT USAGE, SELECT ON SEQUENCE estimate_row_normalization_runs_id_seq TO doc_worker;
