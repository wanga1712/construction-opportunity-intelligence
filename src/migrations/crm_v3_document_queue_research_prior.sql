-- Migration: Add Stage 1 V2 Research Prior fields to document_processing_queue
-- Database: document_intelligence (Document DB on S13)

ALTER TABLE document_processing_queue
    ADD COLUMN IF NOT EXISTS research_prior_model varchar(64),
    ADD COLUMN IF NOT EXISTS research_prior_version varchar(32),
    ADD COLUMN IF NOT EXISTS research_prior_score numeric(6,5),
    ADD COLUMN IF NOT EXISTS research_prior_percentile numeric(6,5),
    ADD COLUMN IF NOT EXISTS research_prior_band varchar(16),
    ADD COLUMN IF NOT EXISTS research_prior_effective_score integer,
    ADD COLUMN IF NOT EXISTS research_prior_scored_at timestamp with time zone;

CREATE INDEX IF NOT EXISTS idx_dpq_research_prior_band ON document_processing_queue(research_prior_band) WHERE status IN ('PENDING', 'PRE_RESEARCH_WAITING');
CREATE INDEX IF NOT EXISTS idx_dpq_research_prior_eff_score ON document_processing_queue(research_prior_effective_score DESC) WHERE status IN ('PENDING', 'PRE_RESEARCH_WAITING');
