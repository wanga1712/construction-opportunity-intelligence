-- GOOD_SUPPLY_FACTS_V1: per-document identity for extraction runs.
-- A procurement can have several source documents with the same file_name
-- (e.g. a top-level appendix and the same appendix inside a contract archive).
-- The old (detail_id, extractor_version) unique key merged them and made their
-- snapshots overwrite each other.

SET LOCAL lock_timeout = '15s';

ALTER TABLE structured_extraction_runs
    ADD COLUMN IF NOT EXISTS source_document_id BIGINT;

-- Old global unique key is replaced by two scoped ones:
--   * document-scoped runs (source_document_id NOT NULL);
--   * legacy runs without a document identity (source_document_id IS NULL).
ALTER TABLE structured_extraction_runs
    DROP CONSTRAINT IF EXISTS uq_extraction_run_detail_version;

CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_procurement_source_extractor
    ON structured_extraction_runs (procurement_id, source_document_id, extractor_version)
    WHERE source_document_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_detail_version_legacy
    ON structured_extraction_runs (detail_id, extractor_version)
    WHERE source_document_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_runs_procurement_source
    ON structured_extraction_runs (procurement_id, source_document_id);
