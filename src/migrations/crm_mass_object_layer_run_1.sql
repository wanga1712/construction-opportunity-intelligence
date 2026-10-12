-- WIP=MASS-CANONICAL-OBJECT-LAYER-RUN-V1
-- Additive schema evolution for the mass canonical object-layer run.
--
-- Apply ONLY via the canonical S13 DDL admin route:
--   ssh <S13_SSH_USER>@S13
--   sudo -n -u postgres psql -d crm -v ON_ERROR_STOP=1 -f <this file>
-- Do NOT apply from Streamlit/runtime.  No medals.  No evidence.  No downloads.
--
-- Additive + idempotent: safe to apply twice.  No table is dropped, no column
-- is removed, no existing row is rewritten.  Base DDL stays owned by
-- src/migrations/crm_procurement_object_classifications_1.sql.
--
-- What changes and why:
--   * the mass run introduces the Qwen fallback path, so the status vocabulary
--     gains RESOLVED_MODEL / MODE_AMBIGUOUS / OBJECT_UNCERTAIN / MODEL_INVALID
--     (section 8 of the WIP contract);
--   * classification_source gains the two model provenances QWEN_OBJECT_V1 and
--     QWEN_MODE_V1;
--   * confidence_class gains MODEL (a model answer is never EXPERT/HIGH);
--   * raw model provenance must be kept separately from the canonical result,
--     so three nullable audit columns are added:
--       mode_source  - which gate produced procurement_mode;
--       model_raw    - the untouched model JSON (canonical axes live in the
--                      dedicated columns above; this is audit only);
--       model_reason - the model's free-text reason.
-- Vocabulary is owned by src/services/object_classification.py and
-- src/services/expert_object_taxonomy.py.  The DB keeps only cheap guards.

-- --- raw model provenance (additive columns) -------------------------------
ALTER TABLE crm_procurement_object_classifications
    ADD COLUMN IF NOT EXISTS mode_source  TEXT;
ALTER TABLE crm_procurement_object_classifications
    ADD COLUMN IF NOT EXISTS model_raw    JSONB;
ALTER TABLE crm_procurement_object_classifications
    ADD COLUMN IF NOT EXISTS model_reason TEXT;

-- --- status vocabulary -----------------------------------------------------
ALTER TABLE crm_procurement_object_classifications
    DROP CONSTRAINT IF EXISTS ck_cpoc_status;
ALTER TABLE crm_procurement_object_classifications
    ADD CONSTRAINT ck_cpoc_status
    CHECK (classification_status IN (
        'RESOLVED_REVIEWED',
        'RESOLVED_HIGH_CONFIDENCE',
        'RESOLVED_MODEL',
        'DIRECT_NA',
        'SERVICE_NA',
        'AMBIGUOUS',
        'MODE_AMBIGUOUS',
        'OBJECT_MISSING',
        'OBJECT_CONFLICT',
        'OBJECT_UNCERTAIN',
        'MODEL_INVALID',
        'OBJECT_NONCANONICAL'
    ));

-- --- source vocabulary -----------------------------------------------------
ALTER TABLE crm_procurement_object_classifications
    DROP CONSTRAINT IF EXISTS ck_cpoc_source;
ALTER TABLE crm_procurement_object_classifications
    ADD CONSTRAINT ck_cpoc_source
    CHECK (classification_source IN (
        'EXPERT_CONFIRMED',
        'REVIEWED',
        'DETERMINISTIC_HIGH_CONFIDENCE',
        'CANONICAL_CURRENT',
        'UNRESOLVED',
        'QWEN_OBJECT_V1',
        'QWEN_MODE_V1'
    ));

-- --- confidence class ------------------------------------------------------
ALTER TABLE crm_procurement_object_classifications
    DROP CONSTRAINT IF EXISTS ck_cpoc_confidence_class;
ALTER TABLE crm_procurement_object_classifications
    ADD CONSTRAINT ck_cpoc_confidence_class
    CHECK (confidence_class IN ('EXPERT', 'MODEL', 'HIGH', 'NONE'));

-- object_applicable is exactly the "resolved" state; RESOLVED_MODEL joins it.
ALTER TABLE crm_procurement_object_classifications
    DROP CONSTRAINT IF EXISTS ck_cpoc_applicable;
ALTER TABLE crm_procurement_object_classifications
    ADD CONSTRAINT ck_cpoc_applicable
    CHECK (
        object_applicable
        = (classification_status IN (
            'RESOLVED_REVIEWED', 'RESOLVED_HIGH_CONFIDENCE', 'RESOLVED_MODEL'
        ))
    );

-- No unresolved status may carry an OBJECT_TYPE.  UNKNOWN stays UNKNOWN.
ALTER TABLE crm_procurement_object_classifications
    DROP CONSTRAINT IF EXISTS ck_cpoc_unresolved_axes;
ALTER TABLE crm_procurement_object_classifications
    ADD CONSTRAINT ck_cpoc_unresolved_axes
    CHECK (
        classification_status NOT IN (
            'AMBIGUOUS', 'MODE_AMBIGUOUS',
            'OBJECT_MISSING', 'OBJECT_CONFLICT',
            'OBJECT_UNCERTAIN', 'MODEL_INVALID',
            'OBJECT_NONCANONICAL'
        )
        OR object_type IS NULL
    );

-- A resolved MODEL row must never masquerade as a human/expert label.
ALTER TABLE crm_procurement_object_classifications
    DROP CONSTRAINT IF EXISTS ck_cpoc_model_provenance;
ALTER TABLE crm_procurement_object_classifications
    ADD CONSTRAINT ck_cpoc_model_provenance
    CHECK (
        confidence_class <> 'MODEL'
        OR classification_source IN ('QWEN_OBJECT_V1', 'QWEN_MODE_V1')
    );

-- --- current-row hygiene ---------------------------------------------------
-- One row per (procurement, version) is the idempotency key (base migration).
-- Re-assert the index in case an older apply predates it.
CREATE UNIQUE INDEX IF NOT EXISTS uix_cpoc_procurement_version
    ON crm_procurement_object_classifications (procurement_id, classification_version);