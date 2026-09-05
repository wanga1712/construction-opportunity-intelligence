-- Canonical Migration 002: Add structured_fact_trust_state to structured_entities and structured_extraction_runs
-- Database: document_intelligence (S13)

ALTER TABLE structured_entities
ADD COLUMN IF NOT EXISTS structured_fact_trust_state VARCHAR(64) DEFAULT 'DEV_EXPOSED';

ALTER TABLE structured_extraction_runs
ADD COLUMN IF NOT EXISTS structured_fact_trust_state VARCHAR(64) DEFAULT 'DEV_EXPOSED';

-- Indexes for fail-closed trust queries
CREATE INDEX IF NOT EXISTS idx_structured_entities_trust_state ON structured_entities (structured_fact_trust_state);
CREATE INDEX IF NOT EXISTS idx_structured_extraction_runs_trust_state ON structured_extraction_runs (structured_fact_trust_state);
