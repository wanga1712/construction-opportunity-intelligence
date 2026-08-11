-- Explicit S13_V2 migration: preserve archive-derived parser identity in result graph.
-- No runtime auto-DDL: apply manually before deploying the matching code.

BEGIN;

ALTER TABLE document_processing_results
    ADD COLUMN IF NOT EXISTS processed_file_name text,
    ADD COLUMN IF NOT EXISTS processed_local_path text,
    ADD COLUMN IF NOT EXISTS archive_member_path text,
    ADD COLUMN IF NOT EXISTS is_archive_member boolean NOT NULL DEFAULT false;

ALTER TABLE document_matches
    ADD COLUMN IF NOT EXISTS archive_member_path text;

CREATE INDEX IF NOT EXISTS idx_dpr_queue_archive_member
    ON document_processing_results (queue_id, archive_member_path)
    WHERE archive_member_path IS NOT NULL;

COMMIT;
