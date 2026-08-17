-- Expert Annotation DDL
-- Phase 1 — crm_v3_expert_annotations + crm_v3_taxonomy_proposals
--
-- INVARIANTS:
--   • procurement_ai_assessments is never mutated by expert annotation.
--   • crm_procurement_category_opportunities is not referenced here.
--   • crm_manual_category_overrides is NOT used in this workflow.
--   • audit writes to crm_manual_assessments_audit (already exists).
--
-- USAGE: psql -d <crm_db> -f ddl_expert_annotations.sql
--        Safe to re-run: all statements use IF NOT EXISTS / DO NOTHING guards.

BEGIN;

-- ════════════════════════════════════════════════════════════════════════════
-- 1. crm_v3_expert_annotations
--    Versioned expert annotation payload per procurement.
--    Optimistic-locking via annotation_version; only one is_current=TRUE row
--    per procurement_id at any time (enforced by partial unique index).
-- ════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS crm_v3_expert_annotations (
    id                  BIGSERIAL        PRIMARY KEY,
    procurement_id      INTEGER          NOT NULL,
    annotation_version  INTEGER          NOT NULL DEFAULT 1,
    is_current          BOOLEAN          NOT NULL DEFAULT TRUE,
    decision_source     TEXT             NOT NULL DEFAULT 'EXPERT_ANNOTATION',
    payload             JSONB            NOT NULL,
    created_by          TEXT             NOT NULL DEFAULT 'unknown',
    created_at          TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

-- Only one current annotation per procurement at any time
CREATE UNIQUE INDEX IF NOT EXISTS uix_expert_annotations_current
    ON crm_v3_expert_annotations (procurement_id)
    WHERE is_current = TRUE;

-- Fast lookup by procurement_id (all versions)
CREATE INDEX IF NOT EXISTS idx_expert_annotations_proc
    ON crm_v3_expert_annotations (procurement_id, annotation_version DESC);

-- GIN index for JSONB lookups (expert_object_type, expert_work_stage, etc.)
CREATE INDEX IF NOT EXISTS idx_expert_annotations_payload
    ON crm_v3_expert_annotations USING GIN (payload);

COMMENT ON TABLE  crm_v3_expert_annotations IS
    'Versioned expert annotations for training dataset V1. '
    'One is_current=TRUE row per procurement. '
    'MODEL RAW (procurement_ai_assessments) is never mutated.';

COMMENT ON COLUMN crm_v3_expert_annotations.payload IS
    'JSONB expert annotation payload (schema_version=1). '
    'Key fields: expert_verdict, expert_object_type, expert_object_subtype, '
    'expert_work_stage, expert_procurement_form, expert_commercial_verdict, '
    'expert_medal, opportunities[], rejected_model_opportunities[], '
    'taxonomy_proposals[], error_reasons[], expert_comment.';

COMMENT ON COLUMN crm_v3_expert_annotations.decision_source IS
    'Always EXPERT_ANNOTATION for rows written by this module. '
    'Reserved for future decision types (e.g. AUTOMATED_VALIDATION).';


-- ════════════════════════════════════════════════════════════════════════════
-- 2. crm_v3_taxonomy_proposals
--    Pending proposals for missing canonical taxonomy values.
--    Status flow: PENDING → APPROVED | REJECTED
--    APPROVED rows are never automatically promoted to canonical registries;
--    that requires a separate human review + migration step.
-- ════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS crm_v3_taxonomy_proposals (
    id                       BIGSERIAL    PRIMARY KEY,
    annotation_id            BIGINT       REFERENCES crm_v3_expert_annotations(id)
                                              ON DELETE SET NULL,
    procurement_id           INTEGER      NOT NULL,
    proposal_type            TEXT         NOT NULL,
    -- ^ CATEGORY | SUBCATEGORY | OBJECT_SECTOR | OBJECT_TYPE
    --   OBJECT_SUBTYPE | WORK_STAGE
    proposed_name            TEXT         NOT NULL,
    proposed_parent_category TEXT,
    expert_comment           TEXT,
    review_status            TEXT         NOT NULL DEFAULT 'PENDING',
    -- ^ PENDING | APPROVED | REJECTED
    reviewed_by              TEXT,
    reviewed_at              TIMESTAMPTZ,
    created_by               TEXT         NOT NULL DEFAULT 'unknown',
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_taxonomy_proposals_status
    ON crm_v3_taxonomy_proposals (review_status, proposal_type);

CREATE INDEX IF NOT EXISTS idx_taxonomy_proposals_annotation
    ON crm_v3_taxonomy_proposals (annotation_id);

-- Check constraint on proposal_type
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'crm_v3_taxonomy_proposals'
          AND constraint_name = 'chk_taxonomy_proposal_type'
    ) THEN
        ALTER TABLE crm_v3_taxonomy_proposals
            ADD CONSTRAINT chk_taxonomy_proposal_type
            CHECK (proposal_type IN (
                'CATEGORY', 'SUBCATEGORY',
                'OBJECT_SECTOR', 'OBJECT_TYPE', 'OBJECT_SUBTYPE',
                'WORK_STAGE'
            ));
    END IF;
END $$;

-- Check constraint on review_status
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'crm_v3_taxonomy_proposals'
          AND constraint_name = 'chk_taxonomy_review_status'
    ) THEN
        ALTER TABLE crm_v3_taxonomy_proposals
            ADD CONSTRAINT chk_taxonomy_review_status
            CHECK (review_status IN ('PENDING', 'APPROVED', 'REJECTED'));
    END IF;
END $$;

COMMENT ON TABLE  crm_v3_taxonomy_proposals IS
    'Pending proposals for missing canonical taxonomy values. '
    'APPROVED rows require a separate human review + migration step before '
    'they appear in any canonical registry. Nothing is promoted automatically.';

COMMENT ON COLUMN crm_v3_taxonomy_proposals.proposal_type IS
    'CATEGORY | SUBCATEGORY | OBJECT_SECTOR | OBJECT_TYPE | OBJECT_SUBTYPE | WORK_STAGE. '
    'object_type / work_stage proposals are for future canonical registry; '
    'they do NOT update procurement_ai_assessments or production routing.';

-- Runtime permissions.  Production DDL is applied by postgres while the CRM
-- process connects as crm_app, so table and sequence grants must be explicit.
GRANT SELECT, INSERT, UPDATE ON crm_v3_expert_annotations TO crm_app;
GRANT USAGE, SELECT ON SEQUENCE crm_v3_expert_annotations_id_seq TO crm_app;
GRANT SELECT, INSERT, UPDATE ON crm_v3_taxonomy_proposals TO crm_app;
GRANT USAGE, SELECT ON SEQUENCE crm_v3_taxonomy_proposals_id_seq TO crm_app;


-- ════════════════════════════════════════════════════════════════════════════
-- 3. crm_manual_assessments_audit — ADD COLUMNS if missing
--    (Table already exists; only extend it.)
-- ════════════════════════════════════════════════════════════════════════════

ALTER TABLE crm_manual_assessments_audit
    ADD COLUMN IF NOT EXISTS original_value   JSONB,
    ADD COLUMN IF NOT EXISTS corrected_value  JSONB,
    ADD COLUMN IF NOT EXISTS approved_for_training BOOLEAN NOT NULL DEFAULT FALSE;

COMMIT;

-- ════════════════════════════════════════════════════════════════════════════
-- VERIFICATION QUERIES (run after applying DDL)
-- ════════════════════════════════════════════════════════════════════════════

-- SELECT table_name, pg_size_pretty(pg_total_relation_size(quote_ident(table_name)))
-- FROM (VALUES
--     ('crm_v3_expert_annotations'),
--     ('crm_v3_taxonomy_proposals'),
--     ('crm_manual_assessments_audit')
-- ) AS t(table_name);
--
-- \d crm_v3_expert_annotations
-- \d crm_v3_taxonomy_proposals
