-- DOCUMENT CLAIM FRESH-FIRST V1

BEGIN;

ALTER TABLE document_processing_queue
    ADD COLUMN IF NOT EXISTS source_start_date date,
    ADD COLUMN IF NOT EXISTS work_tier smallint NOT NULL DEFAULT 2;

CREATE INDEX IF NOT EXISTS idx_dpq_work_tier_start
    ON document_processing_queue (work_tier, source_start_date DESC, id DESC)
    WHERE status IN ('PENDING', 'PRE_RESEARCH_WAITING');

COMMIT;
