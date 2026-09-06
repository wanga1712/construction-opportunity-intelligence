-- Migration 003: Add canary_batch_id UUID to structured_extraction_runs for immutable batch isolation

ALTER TABLE structured_extraction_runs 
ADD COLUMN IF NOT EXISTS canary_batch_id UUID NULL;

CREATE INDEX IF NOT EXISTS idx_structured_extraction_runs_canary_batch 
ON structured_extraction_runs (canary_batch_id);
