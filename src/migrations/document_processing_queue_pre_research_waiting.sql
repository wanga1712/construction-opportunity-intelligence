-- Migration: Add PRE_RESEARCH_WAITING to document_processing_queue status check constraint
-- Database: document_intelligence (Document DB)

ALTER TABLE document_processing_queue
DROP CONSTRAINT IF EXISTS document_processing_queue_status_check;

ALTER TABLE document_processing_queue
ADD CONSTRAINT document_processing_queue_status_check
CHECK (status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED', 'NO_LINKS', 'PRE_RESEARCH_WAITING'));
