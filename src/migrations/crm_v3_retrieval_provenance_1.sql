-- Migration: RETRIEVAL PROVENANCE for raw document matches (WIP point 0)
-- Database: document_intelligence
-- Table owner (verified 2026-10-09): doc_worker. Additive only: NO DELETE,
-- NO RENAME, no ownership change. Apply via the approved DDL admin route
-- (S13 -> `sudo -n -u postgres psql -d document_intelligence`).
--
-- Contract:
--   rule_term    - taxonomy label / rule that triggered the match
--   matched_text - literal document text the matcher actually scored
--   source_span  - raw document slice with char_start/char_end offsets
--   provenance_status - VERIFIED | INVALID | LEGACY_UNVERIFIED (fail-closed)
--
-- Legacy rows written before this contract default to LEGACY_UNVERIFIED and
-- are never treated as verified by downstream consumers.

SET LOCAL lock_timeout = '10s';

ALTER TABLE document_match_details
    ADD COLUMN IF NOT EXISTS rule_term text,
    ADD COLUMN IF NOT EXISTS matched_text text,
    ADD COLUMN IF NOT EXISTS matched_text_normalized text,
    ADD COLUMN IF NOT EXISTS source_span text,
    ADD COLUMN IF NOT EXISTS char_start integer,
    ADD COLUMN IF NOT EXISTS char_end integer,
    ADD COLUMN IF NOT EXISTS document_id bigint,
    ADD COLUMN IF NOT EXISTS table_index integer,
    ADD COLUMN IF NOT EXISTS source_row_index integer,
    ADD COLUMN IF NOT EXISTS source_col_index integer,
    ADD COLUMN IF NOT EXISTS column_letter varchar(8),
    ADD COLUMN IF NOT EXISTS cell_address varchar(16),
    ADD COLUMN IF NOT EXISTS chunk_id text,
    ADD COLUMN IF NOT EXISTS provenance_method varchar(50),
    ADD COLUMN IF NOT EXISTS provenance_reason text,
    ADD COLUMN IF NOT EXISTS provenance_checked_at timestamp with time zone,
    ADD COLUMN IF NOT EXISTS provenance_status varchar(30) NOT NULL DEFAULT 'LEGACY_UNVERIFIED';

-- Legacy label column is preserved as the record of what the old pipeline
-- called the matched term; rule_term becomes the canonical field from now on.
UPDATE document_match_details
   SET rule_term = matched_term
 WHERE rule_term IS NULL
   AND matched_term IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_dmd_provenance_status'
    ) THEN
        ALTER TABLE document_match_details
            ADD CONSTRAINT chk_dmd_provenance_status
            CHECK (provenance_status IN ('VERIFIED', 'INVALID', 'LEGACY_UNVERIFIED'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_dmd_provenance_status
    ON document_match_details (pipeline_generation, provenance_status);
