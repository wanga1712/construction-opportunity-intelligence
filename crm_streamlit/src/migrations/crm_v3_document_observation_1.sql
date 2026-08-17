-- CRM-V3 document observation baseline (learning/instrumentation contract).
-- Apply ONLY via the canonical S13 DDL admin route:
--   ssh -i C:\Users\Lenovo\.ssh\id_ed25519_codex_worker sergey@10.8.0.13
--   then: sudo -n -u postgres psql -d crm -f <this file>
-- Do NOT apply from Streamlit/runtime. Do NOT start document workers.
-- Do NOT download or process the calibration set in this migration.

CREATE TABLE IF NOT EXISTS crm_v3_document_observations (
    id                              BIGSERIAL PRIMARY KEY,
    observation_key                 TEXT NOT NULL,
    procurement_id                  BIGINT NOT NULL,
    source_contour                  TEXT,
    source_document_id              TEXT,
    source_document_url             TEXT,
    document_title                  TEXT,
    source_document_type            TEXT,
    file_extension                  TEXT,
    mime_type                       TEXT,
    source_section                  TEXT,
    procurement_form                TEXT,
    object_type                     TEXT,
    object_context                  TEXT,
    commercial_candidate_categories JSONB NOT NULL DEFAULT '[]'::jsonb,
    okpd_context                    TEXT,
    procurement_lifecycle           TEXT,
    document_ordinal                INTEGER,
    document_count                  INTEGER,
    download_status                 TEXT,
    parse_status                    TEXT,
    file_size                       BIGINT,
    page_count                      INTEGER,
    text_length                     INTEGER,
    commercial_evidence_found       BOOLEAN,
    evidence_count                  INTEGER,
    matched_categories              JSONB NOT NULL DEFAULT '[]'::jsonb,
    matched_subcategories           JSONB NOT NULL DEFAULT '[]'::jsonb,
    matched_terms                   JSONB NOT NULL DEFAULT '[]'::jsonb,
    product_mentions                JSONB NOT NULL DEFAULT '[]'::jsonb,
    specification_evidence          BOOLEAN,
    estimate_evidence               BOOLEAN,
    volume_quantity_evidence        BOOLEAN,
    numeric_unit_evidence           BOOLEAN,
    usefulness_label                TEXT NOT NULL DEFAULT 'UNOBSERVED',
    acquisition_policy              TEXT NOT NULL,
    acquisition_policy_version      TEXT NOT NULL,
    extractor_version               TEXT,
    matcher_version                 TEXT,
    taxonomy_version                TEXT,
    selector_model_version          TEXT,
    calibration_truth               BOOLEAN NOT NULL DEFAULT FALSE,
    observed_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uix_crm_v3_document_observations_key
    ON crm_v3_document_observations (observation_key);

CREATE INDEX IF NOT EXISTS idx_crm_v3_document_observations_proc
    ON crm_v3_document_observations (procurement_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_crm_v3_document_observations_policy
    ON crm_v3_document_observations (acquisition_policy, usefulness_label);

CREATE INDEX IF NOT EXISTS idx_crm_v3_document_observations_type
    ON crm_v3_document_observations (source_document_type);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'crm_v3_document_observations'
          AND constraint_name = 'chk_crm_v3_doc_obs_policy'
    ) THEN
        ALTER TABLE crm_v3_document_observations
            ADD CONSTRAINT chk_crm_v3_doc_obs_policy
            CHECK (acquisition_policy IN (
                'EXHAUSTIVE',
                'MODEL_SELECTED',
                'RANDOM_EXPLORATION',
                'HISTORICAL_FILTERED'
            ));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'crm_v3_document_observations'
          AND constraint_name = 'chk_crm_v3_doc_obs_usefulness'
    ) THEN
        ALTER TABLE crm_v3_document_observations
            ADD CONSTRAINT chk_crm_v3_doc_obs_usefulness
            CHECK (usefulness_label IN (
                'USEFUL_COMMERCIAL_EVIDENCE',
                'PARSED_NO_COMMERCIAL_EVIDENCE',
                'DOWNLOAD_FAILED',
                'PARSE_FAILED',
                'UNSUPPORTED_FORMAT',
                'EMPTY_DOCUMENT',
                'DUPLICATE_DOCUMENT',
                'UNOBSERVED'
            ));
    END IF;
END $$;

COMMENT ON TABLE crm_v3_document_observations IS
    'Document acquisition observations for a future DOCUMENT_VALUE_MODEL. '
    'Outcome labels are factual processing results, not selector opinion. '
    'calibration_truth is TRUE only for EXHAUSTIVE and RANDOM_EXPLORATION. '
    'MODEL_SELECTED and HISTORICAL_FILTERED are never unbiased calibration truth. '
    'source_document_type is retained as-is; title is a signal, not an inferred class. '
    'Runtime must not CREATE this table.';

COMMENT ON COLUMN crm_v3_document_observations.calibration_truth IS
    'Unbiased calibration: EXHAUSTIVE=TRUE, RANDOM_EXPLORATION=TRUE, '
    'MODEL_SELECTED=FALSE, HISTORICAL_FILTERED=FALSE.';

COMMENT ON COLUMN crm_v3_document_observations.usefulness_label IS
    'Factual outcome: USEFUL_COMMERCIAL_EVIDENCE | PARSED_NO_COMMERCIAL_EVIDENCE | '
    'DOWNLOAD_FAILED | PARSE_FAILED | UNSUPPORTED_FORMAT | EMPTY_DOCUMENT | '
    'DUPLICATE_DOCUMENT | UNOBSERVED. Failures are not collapsed into no-evidence.';

COMMENT ON COLUMN crm_v3_document_observations.source_document_type IS
    'Source metadata type only. NULL means absent; do not infer a class from title.';

GRANT SELECT, INSERT, UPDATE ON crm_v3_document_observations TO crm_app;
GRANT USAGE, SELECT ON SEQUENCE crm_v3_document_observations_id_seq TO crm_app;
