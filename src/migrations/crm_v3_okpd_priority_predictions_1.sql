-- Additive migration for future shadow prediction storage of OKPD research priority.
-- WIP: CRM-V3-OKPD-PRIOR-LEARNING-V1
-- Note: MIGRATION_IMPLEMENTED=YES, PRODUCTION_MIGRATION_APPLIED=NO (offline/shadow preview only).

CREATE TABLE IF NOT EXISTS crm_v3_okpd_priority_predictions (
    id BIGSERIAL PRIMARY KEY,
    procurement_id BIGINT NOT NULL,
    model_name VARCHAR(80) NOT NULL DEFAULT 'okpd_research_hit_v1',
    model_version VARCHAR(40) NOT NULL DEFAULT 'v1',
    trained_at TIMESTAMPTZ NULL,
    dataset_snapshot_sha256 VARCHAR(64) NULL,
    p_research_hit NUMERIC(6, 4) NOT NULL,
    priority_percentile NUMERIC(6, 4) NOT NULL,
    priority_band VARCHAR(20) NOT NULL,
    okpd_code_raw VARCHAR(80) NULL,
    okpd_root VARCHAR(40) NOT NULL,
    okpd_level2 VARCHAR(40) NOT NULL,
    okpd_level3 VARCHAR(40) NOT NULL,
    okpd_full VARCHAR(80) NOT NULL,
    prediction_created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    shadow_only BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_crm_v3_okpd_priority_proc_version UNIQUE (procurement_id, model_version)
);

CREATE INDEX IF NOT EXISTS idx_crm_v3_okpd_priority_band
    ON crm_v3_okpd_priority_predictions (priority_band);

CREATE INDEX IF NOT EXISTS idx_crm_v3_okpd_priority_score
    ON crm_v3_okpd_priority_predictions (p_research_hit DESC);
