-- Narrow reconciliation for a partially applied expert-annotation schema.
-- Run only after verify_expert_annotation_schema.sql proves missing objects.
-- Does not alter owners and does not touch MODEL RAW or canonical taxonomy.

BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS crm_v3_taxonomy_proposals (
    id                       BIGSERIAL    PRIMARY KEY,
    annotation_id            BIGINT       REFERENCES crm_v3_expert_annotations(id)
                                              ON DELETE SET NULL,
    procurement_id           BIGINT       NOT NULL,
    proposal_type            TEXT         NOT NULL,
    proposed_name            TEXT         NOT NULL,
    proposed_parent_category TEXT,
    expert_comment           TEXT,
    review_status            TEXT         NOT NULL DEFAULT 'PENDING',
    reviewed_by              TEXT,
    reviewed_at              TIMESTAMPTZ,
    created_by               TEXT         NOT NULL DEFAULT 'unknown',
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_taxonomy_proposal_type CHECK (proposal_type IN (
        'CATEGORY', 'SUBCATEGORY', 'OBJECT_SECTOR', 'OBJECT_TYPE',
        'OBJECT_SUBTYPE', 'WORK_STAGE'
    )),
    CONSTRAINT chk_taxonomy_review_status CHECK (
        review_status IN ('PENDING', 'APPROVED', 'REJECTED')
    )
);

CREATE INDEX IF NOT EXISTS idx_taxonomy_proposals_status
    ON crm_v3_taxonomy_proposals (review_status, proposal_type);
CREATE INDEX IF NOT EXISTS idx_taxonomy_proposals_annotation
    ON crm_v3_taxonomy_proposals (annotation_id);

COMMENT ON TABLE crm_v3_taxonomy_proposals IS
    'Pending expert proposals only; never auto-promoted to canonical taxonomy.';

GRANT SELECT, INSERT, UPDATE ON crm_v3_expert_annotations TO crm_app;
GRANT USAGE, SELECT ON SEQUENCE crm_v3_expert_annotations_id_seq TO crm_app;
GRANT SELECT, INSERT, UPDATE ON crm_v3_taxonomy_proposals TO crm_app;
GRANT USAGE, SELECT ON SEQUENCE crm_v3_taxonomy_proposals_id_seq TO crm_app;

COMMIT;
