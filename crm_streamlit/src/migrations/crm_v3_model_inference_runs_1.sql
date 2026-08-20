-- CRM-V3-MODEL-AUTHORITY-RESTORATION-1 / Phase 6A
-- Additive immutable model inference run storage.
-- Apply ONLY via the canonical S13 DDL admin route:
--   approved SSH host alias from PROJECT_OPERATING_RULES.md, then:
--   sudo -n -u postgres psql -d crm -f <this file>
-- Do NOT apply from Streamlit/runtime.
-- Do NOT change table ownership.
-- Do NOT synthesize historical inference runs.

CREATE TABLE IF NOT EXISTS crm_v3_model_inference_runs (
    id                      BIGSERIAL PRIMARY KEY,
    procurement_id          BIGINT NOT NULL,
    run_kind                TEXT NOT NULL
        CHECK (run_kind IN ('PRODUCTION', 'SHADOW')),
    model_name              TEXT,
    model_version           TEXT,
    prompt_version          TEXT,
    schema_version          TEXT,
    prompt_hash             TEXT,
    raw_model_text          TEXT,
    raw_model_sha256        TEXT,
    raw_model_json          JSONB,
    parse_status            TEXT NOT NULL
        CHECK (parse_status IN (
            'MODEL_CALL_FAILED',
            'RAW_RECEIVED_PARSE_FAILED',
            'PARSED_OK',
            'NOT_ATTEMPTED'
        )),
    validated_model_result  JSONB,
    validated_model_sha256  TEXT,
    validation_status       TEXT NOT NULL
        CHECK (validation_status IN (
            'NOT_ATTEMPTED',
            'PARSED_SCHEMA_INVALID',
            'VALIDATED_SUCCESS',
            'POSTPROCESSING_FAILED'
        )),
    validation_errors       JSONB NOT NULL DEFAULT '[]'::jsonb,
    ollama_metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
    retry_count             INTEGER NOT NULL DEFAULT 0,
    source_attempt_id       BIGINT,
    run_status              TEXT NOT NULL DEFAULT 'OPEN'
        CHECK (run_status IN (
            'OPEN',
            'MODEL_CALL_FAILED',
            'RAW_RECEIVED_PARSE_FAILED',
            'PARSED_SCHEMA_INVALID',
            'VALIDATED_SUCCESS',
            'POSTPROCESSING_FAILED',
            'COMPLETED'
        )),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crm_v3_model_inference_runs_proc
    ON crm_v3_model_inference_runs (procurement_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_crm_v3_model_inference_runs_kind
    ON crm_v3_model_inference_runs (run_kind, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_crm_v3_model_inference_runs_raw_sha
    ON crm_v3_model_inference_runs (raw_model_sha256)
    WHERE raw_model_sha256 IS NOT NULL;

-- Link assessments → immutable inference runs (historical rows stay NULL).
ALTER TABLE procurement_ai_assessments
    ADD COLUMN IF NOT EXISTS inference_run_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'procurement_ai_assessments'
          AND constraint_name = 'fk_procurement_ai_assessments_inference_run'
    ) THEN
        ALTER TABLE procurement_ai_assessments
            ADD CONSTRAINT fk_procurement_ai_assessments_inference_run
            FOREIGN KEY (inference_run_id)
            REFERENCES crm_v3_model_inference_runs (id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_procurement_ai_assessments_inference_run
    ON procurement_ai_assessments (inference_run_id)
    WHERE inference_run_id IS NOT NULL;

-- Application-layer immutability is primary. Optional-level protection for raw/validated
-- payload columns: block UPDATE of immutable model payload fields after insert.
CREATE OR REPLACE FUNCTION crm_v3_model_inference_runs_immutable_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.raw_model_text IS DISTINCT FROM OLD.raw_model_text
           OR NEW.raw_model_sha256 IS DISTINCT FROM OLD.raw_model_sha256
           OR NEW.raw_model_json IS DISTINCT FROM OLD.raw_model_json
           OR NEW.validated_model_result IS DISTINCT FROM OLD.validated_model_result
           OR NEW.validated_model_sha256 IS DISTINCT FROM OLD.validated_model_sha256
           OR NEW.prompt_hash IS DISTINCT FROM OLD.prompt_hash
           OR NEW.procurement_id IS DISTINCT FROM OLD.procurement_id
           OR NEW.run_kind IS DISTINCT FROM OLD.run_kind
        THEN
            RAISE EXCEPTION
                'crm_v3_model_inference_runs immutable payload fields cannot be updated (id=%)',
                OLD.id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_crm_v3_model_inference_runs_immutable
    ON crm_v3_model_inference_runs;
CREATE TRIGGER trg_crm_v3_model_inference_runs_immutable
    BEFORE UPDATE ON crm_v3_model_inference_runs
    FOR EACH ROW
    EXECUTE FUNCTION crm_v3_model_inference_runs_immutable_guard();
