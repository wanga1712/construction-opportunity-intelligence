BEGIN;

CREATE TABLE IF NOT EXISTS crm_v3_inference_jobs (
    id BIGSERIAL PRIMARY KEY,
    procurement_id BIGINT NOT NULL REFERENCES crm_procurements(id),
    run_kind TEXT NOT NULL,
    model_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    requested_by TEXT NOT NULL,
    request_source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    claimed_by TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    last_error TEXT,
    inference_run_id BIGINT REFERENCES crm_v3_model_inference_runs(id),
    retry_of_job_id BIGINT REFERENCES crm_v3_inference_jobs(id),
    CONSTRAINT crm_v3_inference_jobs_status_ck
      CHECK (status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
    CONSTRAINT crm_v3_inference_jobs_attempts_ck
      CHECK (attempt_count >= 0 AND max_attempts > 0),
    CONSTRAINT crm_v3_inference_jobs_fingerprint_ck
      CHECK (length(input_fingerprint) = 64)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_crm_v3_inference_jobs_active_identity
ON crm_v3_inference_jobs (
    procurement_id, model_version, prompt_version, run_kind, input_fingerprint
)
WHERE status IN ('QUEUED','RUNNING');

CREATE INDEX IF NOT EXISTS ix_crm_v3_inference_jobs_claim
ON crm_v3_inference_jobs (status, available_at, created_at, id);

CREATE INDEX IF NOT EXISTS ix_crm_v3_inference_jobs_stale
ON crm_v3_inference_jobs (heartbeat_at, id) WHERE status='RUNNING';

CREATE INDEX IF NOT EXISTS ix_crm_v3_inference_jobs_procurement
ON crm_v3_inference_jobs (procurement_id, created_at DESC);

COMMIT;
