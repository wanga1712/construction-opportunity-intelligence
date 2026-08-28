-- CRM-V3 Autonomous Learning Loop 1 Database Schema.
-- Apply ONLY via the canonical S13 DDL admin route:
--   ssh -i <SSH_KEY> sergey@10.8.0.13
--   then: sudo -n -u postgres psql -d crm -f src/migrations/crm_v3_autonomous_learning_loop_1.sql

CREATE TABLE IF NOT EXISTS crm_v3_product_findings (
    id                              BIGSERIAL PRIMARY KEY,
    procurement_id                  BIGINT NOT NULL,
    procurement_number              TEXT,
    category_code                   TEXT,
    subcategory_code                TEXT,
    product_type                    TEXT,
    product_name_normalized         TEXT,
    brand                           TEXT,
    manufacturer                    TEXT,
    model                           TEXT,
    article                         TEXT,
    sku                             TEXT,
    raw_description                 TEXT,
    quantity                        NUMERIC,
    unit                            TEXT,
    unit_price                      NUMERIC,
    total_price                     NUMERIC,
    currency                        TEXT,
    document_id                     BIGINT,
    source_document_id              TEXT,
    document_name                   TEXT,
    document_url                    TEXT,
    page                            TEXT,
    sheet                           TEXT,
    section                         TEXT,
    table_name                      TEXT,
    row_num                         TEXT,
    col_num                         TEXT,
    position_number                 TEXT,
    paragraph                       TEXT,
    source_locator_json             JSONB,
    evidence_text                   TEXT,
    extractor_role                  TEXT,
    extraction_confidence           NUMERIC,
    model_run_id                    BIGINT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crm_v3_product_findings_proc ON crm_v3_product_findings(procurement_id);
CREATE INDEX IF NOT EXISTS idx_crm_v3_product_findings_cat ON crm_v3_product_findings(category_code);

CREATE TABLE IF NOT EXISTS crm_v3_reward_ledger (
    id                              BIGSERIAL PRIMARY KEY,
    procurement_id                  BIGINT NOT NULL,
    field                           TEXT,
    event_type                      TEXT,
    hunter_run_id                   BIGINT,
    auditor_run_id                  BIGINT,
    old_model_value                 TEXT,
    auditor_value                   TEXT,
    human_value                     TEXT,
    reward_config_version           TEXT,
    reward                          NUMERIC,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crm_v3_reward_ledger_proc ON crm_v3_reward_ledger(procurement_id);

CREATE TABLE IF NOT EXISTS crm_v3_autonomous_analysis_traces (
    id                              BIGSERIAL PRIMARY KEY,
    procurement_id                  BIGINT NOT NULL,
    source_snapshot_hash            TEXT,
    document_set_hash               TEXT,
    extracted_evidence_hash         TEXT,
    hunter_run_id                   BIGINT,
    auditor_run_id                  BIGINT,
    consensus_state                 TEXT,
    human_feedback_id               BIGINT,
    reward_event_id                 BIGINT,
    dataset_target_id               BIGINT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crm_v3_analysis_traces_proc ON crm_v3_autonomous_analysis_traces(procurement_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON crm_v3_product_findings TO crm_app;
GRANT USAGE, SELECT ON SEQUENCE crm_v3_product_findings_id_seq TO crm_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON crm_v3_reward_ledger TO crm_app;
GRANT USAGE, SELECT ON SEQUENCE crm_v3_reward_ledger_id_seq TO crm_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON crm_v3_autonomous_analysis_traces TO crm_app;
GRANT USAGE, SELECT ON SEQUENCE crm_v3_autonomous_analysis_traces_id_seq TO crm_app;
