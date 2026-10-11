-- Semantic layer: confirmed category facts (deduped) built from structured_entities.
-- Semantic identity deliberately EXCLUDES page/sheet/row so that the same position
-- duplicated across tables of one document collapses, while genuinely different
-- positions of the same material stay separate.

CREATE TABLE IF NOT EXISTS confirmed_category_facts (
    id                    bigserial PRIMARY KEY,
    semantic_key          text NOT NULL UNIQUE,
    procurement_id        bigint NOT NULL,
    category_code         text NOT NULL,
    source_document_id    bigint,
    physical_download_key text,
    material_normalized   text,
    quantity_value        numeric,
    unit_normalized       text,
    measurement_family    text,
    unit_price_value      numeric,
    line_total_value      numeric,
    entity_id             bigint,
    member_entity_ids     bigint[],
    collapsed_count       integer NOT NULL DEFAULT 1,
    page_or_sheet         text,
    row_or_line           text,
    source_quote          text,
    extractor_version     text,
    normalizer_version    text,
    built_at              timestamptz NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_confirmed_facts_pid_cat
    ON confirmed_category_facts (procurement_id, category_code);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_doc
    ON confirmed_category_facts (source_document_id);
