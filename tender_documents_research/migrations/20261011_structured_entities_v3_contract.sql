-- EMBEDDED_EXTRACTION_NORMALIZATION_V1: structured fact contract extension.
-- Additive. Owner: doc_worker (DDL via approved postgres route).

-- Provenance + normalization columns on structured_entities.
ALTER TABLE structured_entities
    ADD COLUMN IF NOT EXISTS measurement_family      text,
    ADD COLUMN IF NOT EXISTS source_document_id      bigint,
    ADD COLUMN IF NOT EXISTS physical_download_key   text,
    ADD COLUMN IF NOT EXISTS page_or_sheet           text,
    ADD COLUMN IF NOT EXISTS row_or_line             text,
    ADD COLUMN IF NOT EXISTS extractor_version       text,
    ADD COLUMN IF NOT EXISTS normalizer_version      text;

COMMENT ON COLUMN structured_entities.measurement_family IS
    'COUNT|AREA|LENGTH|MASS|VOLUME - quantity cohorts compare only compatible units';
COMMENT ON COLUMN structured_entities.source_document_id IS
    'document_files.id the fact was extracted from (provenance)';

-- Extraction can exist without a keyword match detail (provenance is carried by
-- source_document_id/file/page/row instead). detail_id stays when available.
ALTER TABLE structured_extraction_runs ALTER COLUMN detail_id DROP NOT NULL;
ALTER TABLE structured_entities      ALTER COLUMN detail_id DROP NOT NULL;

CREATE INDEX IF NOT EXISTS idx_r4_entities_source_doc
    ON structured_entities (source_document_id)
    WHERE source_document_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_r4_entities_family
    ON structured_entities (measurement_family)
    WHERE measurement_family IS NOT NULL;
