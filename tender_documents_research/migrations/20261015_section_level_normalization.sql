-- SECTION_LEVEL_NORMALIZATION_V1 Phase 2
-- Additive, idempotent section context for structured_entities.
-- No scoring/medal/queue changes. No data rewrite.

SET LOCAL lock_timeout = '15s';

ALTER TABLE structured_entities
    ADD COLUMN IF NOT EXISTS section_code               TEXT,
    ADD COLUMN IF NOT EXISTS section_name               TEXT,
    ADD COLUMN IF NOT EXISTS section_total_price_value  NUMERIC,
    ADD COLUMN IF NOT EXISTS section_total_price_raw    TEXT,
    ADD COLUMN IF NOT EXISTS section_total_source       TEXT;

COMMENT ON COLUMN structured_entities.section_code IS
    'Deterministic section identity: sheet + normalized section label';
COMMENT ON COLUMN structured_entities.section_name IS
    'Human-readable section name from source_quote column A / section label';
COMMENT ON COLUMN structured_entities.section_total_price_value IS
    'Section total from explicit section total (SECTION_TOTAL) or computed child sum (COMPUTED_SUM)';
COMMENT ON COLUMN structured_entities.section_total_price_raw IS
    'Raw quote for the section total row';
COMMENT ON COLUMN structured_entities.section_total_source IS
    'SECTION_TOTAL or COMPUTED_SUM; DOCUMENT_TOTAL is not written here';

CREATE INDEX IF NOT EXISTS idx_r4_entities_section
    ON structured_entities (procurement_id, section_code)
    WHERE section_code IS NOT NULL;
