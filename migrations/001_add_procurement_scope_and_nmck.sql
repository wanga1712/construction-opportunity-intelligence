-- Canonical Migration 001: Add Procurement Scope and NMCK fields
-- Database: document_intelligence (S13)

ALTER TABLE document_processing_queue
ADD COLUMN IF NOT EXISTS procurement_scope_type VARCHAR,
ADD COLUMN IF NOT EXISTS procurement_scope_confidence NUMERIC,
ADD COLUMN IF NOT EXISTS procurement_scope_source VARCHAR,
ADD COLUMN IF NOT EXISTS procurement_scope_reason TEXT,
ADD COLUMN IF NOT EXISTS procurement_scope_model VARCHAR,
ADD COLUMN IF NOT EXISTS procurement_scope_version VARCHAR,
ADD COLUMN IF NOT EXISTS procurement_scope_scored_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS normalized_nmck_rub NUMERIC;

ALTER TABLE structured_entities
ADD COLUMN IF NOT EXISTS product_relation VARCHAR,
ADD COLUMN IF NOT EXISTS product_relation_confidence NUMERIC,
ADD COLUMN IF NOT EXISTS product_relation_source VARCHAR,
ADD COLUMN IF NOT EXISTS product_relation_reason TEXT,
ADD COLUMN IF NOT EXISTS product_relation_scored_at TIMESTAMPTZ;

-- Index for efficient effective band pool queries
CREATE INDEX IF NOT EXISTS idx_dpq_scope_nmck ON document_processing_queue (procurement_scope_type, normalized_nmck_rub);
