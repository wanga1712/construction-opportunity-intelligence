-- Memory of per-document extraction outcome (version-scoped).
-- Lets REDOWNLOAD skip documents that provably yield nothing for the CURRENT
-- extractor version, and re-open them automatically when the version changes.

CREATE TABLE IF NOT EXISTS document_extraction_outcomes (
    id                    bigserial PRIMARY KEY,
    source_document_id    bigint NOT NULL,
    procurement_id        bigint NOT NULL,
    category_code         text,
    track                 text,
    document_name         text,
    artifact_class        text,
    extractor_version     text NOT NULL,
    normalizer_version    text,
    outcome               text NOT NULL,   -- FACTS_FOUND | NO_FACTS | PARSE_FAILED | CORRUPT | UNSUPPORTED | HEAVY_*
    facts_found           integer NOT NULL DEFAULT 0,
    member_count          integer,
    bytes                 bigint,
    reason                text,
    files_parsed          integer NOT NULL DEFAULT 0,
    files_failed          integer NOT NULL DEFAULT 0,
    updated_at            timestamptz NOT NULL DEFAULT NOW(),
    created_at            timestamptz NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_extraction_outcome_doc_version
    ON document_extraction_outcomes (source_document_id, extractor_version, COALESCE(category_code, ''));
CREATE INDEX IF NOT EXISTS idx_extraction_outcome_kind
    ON document_extraction_outcomes (outcome);
CREATE INDEX IF NOT EXISTS idx_extraction_outcome_pid
    ON document_extraction_outcomes (procurement_id);
