-- Preserve CRM end_date as the document-queue submission deadline.
-- Database: document_intelligence (Document DB on S13)

ALTER TABLE document_processing_queue
    ADD COLUMN IF NOT EXISTS submission_end_at timestamp with time zone;

CREATE INDEX IF NOT EXISTS idx_dpq_submission_end_at
    ON document_processing_queue (submission_end_at)
    WHERE status IN ('PENDING', 'PRE_RESEARCH_WAITING');
