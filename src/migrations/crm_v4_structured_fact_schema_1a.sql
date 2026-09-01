-- CRM V4 Structured Product Fact Schema Closure Migration
-- Migration: crm_v4_structured_fact_schema_1a.sql
-- Additive & Idempotent Schema Closure for R4 Field-Level Provenance & Explicit Defaults

-- 1. Create Field Evidence Table (Section 8)
CREATE TABLE IF NOT EXISTS structured_entity_field_evidence (
    id BIGSERIAL PRIMARY KEY,
    entity_id BIGINT NOT NULL REFERENCES structured_entities(id) ON DELETE CASCADE,
    run_id BIGINT NOT NULL REFERENCES structured_extraction_runs(id) ON DELETE CASCADE,
    field_name VARCHAR(100) NOT NULL,
    source_quote TEXT NOT NULL,
    evidence_fingerprint VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_field_evidence_fingerprint UNIQUE (entity_id, evidence_fingerprint)
);

-- 2. Drop Implicit Defaults on Source Validator Provenance (Section 5)
ALTER TABLE structured_extraction_runs ALTER COLUMN source_validator_name DROP DEFAULT;
ALTER TABLE structured_extraction_runs ALTER COLUMN source_validator_version DROP DEFAULT;
ALTER TABLE structured_extraction_runs ALTER COLUMN source_validation_method DROP DEFAULT;

-- 3. Drop Implicit Default on Currency Code (Section 13)
ALTER TABLE structured_entities ALTER COLUMN currency_code DROP DEFAULT;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_r4_field_ev_entity_id ON structured_entity_field_evidence(entity_id);
CREATE INDEX IF NOT EXISTS idx_r4_field_ev_name ON structured_entity_field_evidence(field_name);
