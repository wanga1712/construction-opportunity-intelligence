-- Migration 006: persist the source-authority eligibility decision on each run

ALTER TABLE structured_extraction_runs
    ADD COLUMN IF NOT EXISTS source_available BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS extraction_eligible BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE structured_entities
    ALTER COLUMN entity_type SET DEFAULT 'UNKNOWN';
