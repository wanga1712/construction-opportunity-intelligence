-- Migration: Separate Raw Document Matches from Confirmed Factual Evidence
-- Database: document_intelligence
-- Generation: S13_V4_EXHAUSTIVE_CONTEXT

ALTER TABLE document_match_details
    ADD COLUMN IF NOT EXISTS match_method VARCHAR(50) DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS validation_status VARCHAR(30) DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS validation_method VARCHAR(50) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS validation_reason TEXT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS validated_at TIMESTAMP WITH TIME ZONE DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS validator_name VARCHAR(100) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS validator_version VARCHAR(50) DEFAULT NULL;

ALTER TABLE document_evidence
    ADD COLUMN IF NOT EXISTS validation_status VARCHAR(30) DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS validation_version VARCHAR(50) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS validation_method VARCHAR(50) DEFAULT NULL;

-- Ensure default on document_evidence is fail-closed (UNKNOWN)
ALTER TABLE document_evidence
    ALTER COLUMN validation_status SET DEFAULT 'UNKNOWN',
    ALTER COLUMN validation_version SET DEFAULT NULL;

-- Mark ONLY legacy pre-barrier evidence as unvalidated.
-- IDEMPOTENT: Does NOT touch new v1 confirmed evidence (where validation_version IS NOT NULL or validation_method != 'legacy_pre_r3_3').
UPDATE document_evidence
SET validation_status = 'LEGACY_UNVALIDATED',
    validation_method = 'legacy_pre_r3_3'
WHERE validation_status IS NULL
   OR (validation_version IS NULL AND (validation_method IS NULL OR validation_method = 'legacy_pre_r3_3'));
