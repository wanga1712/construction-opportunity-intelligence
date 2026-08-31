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
    ADD COLUMN IF NOT EXISTS validation_status VARCHAR(30) DEFAULT 'CONFIRMED',
    ADD COLUMN IF NOT EXISTS validation_version VARCHAR(50) DEFAULT 'v1',
    ADD COLUMN IF NOT EXISTS validation_method VARCHAR(50) DEFAULT NULL;

-- Mark legacy evidence as unvalidated so historical unvalidated hits do not pretend to be confirmed facts
UPDATE document_evidence
SET validation_status = 'LEGACY_UNVALIDATED',
    validation_method = 'legacy_pre_r3_3'
WHERE validation_status IS NULL OR validation_status = 'CONFIRMED';
