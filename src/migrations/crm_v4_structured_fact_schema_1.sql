-- CRM V4 Structured Product & Fact Extraction Schema Migration
-- Migration: crm_v4_structured_fact_schema_1.sql
-- Additive & Idempotent Schema for R4 Structured Fact Storage

-- 1. Structured Extraction Runs
CREATE TABLE IF NOT EXISTS structured_extraction_runs (
    id BIGSERIAL PRIMARY KEY,
    detail_id BIGINT NOT NULL REFERENCES document_match_details(id) ON DELETE CASCADE,
    match_id BIGINT REFERENCES document_matches(id) ON DELETE SET NULL,
    procurement_id BIGINT NOT NULL,
    queue_id BIGINT,
    category_code VARCHAR(100) NOT NULL,
    subcategory_code VARCHAR(100),
    document_name TEXT,
    archive_member_path TEXT,
    page_or_sheet VARCHAR(255),
    row_number INT,
    source_text_snapshot TEXT NOT NULL,
    source_text_sha256 VARCHAR(64) NOT NULL,
    source_validator_name VARCHAR(100) NOT NULL DEFAULT 'context_validator',
    source_validator_version VARCHAR(50) NOT NULL DEFAULT 'v4',
    source_validation_method VARCHAR(100) NOT NULL DEFAULT 'QWEN_CONTEXT_V4',
    extractor_name VARCHAR(100) NOT NULL DEFAULT 'structured_fact_extractor',
    extractor_version VARCHAR(50) NOT NULL DEFAULT 'v1',
    extraction_method VARCHAR(100) NOT NULL DEFAULT 'QWEN_STRUCTURED_FACT_V1',
    prompt_version VARCHAR(50) NOT NULL DEFAULT 'structured_fact_v1',
    model_name VARCHAR(100),
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    raw_response JSONB,
    error_code VARCHAR(100),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT uq_extraction_run_detail_version UNIQUE (detail_id, extractor_version)
);

-- 2. Structured Entities (Product / Material / Equipment / Technology / Work)
CREATE TABLE IF NOT EXISTS structured_entities (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES structured_extraction_runs(id) ON DELETE CASCADE,
    detail_id BIGINT NOT NULL REFERENCES document_match_details(id) ON DELETE CASCADE,
    procurement_id BIGINT NOT NULL,
    category_code VARCHAR(100) NOT NULL,
    subcategory_code VARCHAR(100),
    entity_fingerprint VARCHAR(64) NOT NULL,
    entity_type VARCHAR(50) NOT NULL DEFAULT 'PRODUCT',
    manufacturer_raw TEXT,
    manufacturer_normalized TEXT,
    brand_raw TEXT,
    brand_normalized TEXT,
    product_line_raw TEXT,
    product_line_normalized TEXT,
    product_name_raw TEXT NOT NULL,
    product_name_normalized TEXT,
    model_article_raw TEXT,
    model_article_normalized TEXT,
    quantity_value NUMERIC,
    quantity_unit_raw VARCHAR(100),
    quantity_unit_normalized VARCHAR(100),
    unit_price_value NUMERIC,
    total_price_value NUMERIC,
    currency_code VARCHAR(10) DEFAULT 'RUB',
    source_quote TEXT NOT NULL,
    confidence NUMERIC(4,3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_entity_run_fingerprint UNIQUE (run_id, entity_fingerprint)
);

-- 3. Structured Attributes (Arbitrary Technical & Commercial Characteristics)
CREATE TABLE IF NOT EXISTS structured_attributes (
    id BIGSERIAL PRIMARY KEY,
    entity_id BIGINT NOT NULL REFERENCES structured_entities(id) ON DELETE CASCADE,
    run_id BIGINT NOT NULL REFERENCES structured_extraction_runs(id) ON DELETE CASCADE,
    attribute_fingerprint VARCHAR(64) NOT NULL,
    attribute_name VARCHAR(150) NOT NULL,
    attribute_name_normalized VARCHAR(150) NOT NULL,
    raw_value TEXT NOT NULL,
    normalized_value TEXT,
    numeric_value NUMERIC,
    unit_raw VARCHAR(50),
    unit_normalized VARCHAR(50),
    source_quote TEXT NOT NULL,
    confidence NUMERIC(4,3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_attribute_entity_fingerprint UNIQUE (entity_id, attribute_fingerprint)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_r4_runs_detail_id ON structured_extraction_runs(detail_id);
CREATE INDEX IF NOT EXISTS idx_r4_runs_procurement_id ON structured_extraction_runs(procurement_id);
CREATE INDEX IF NOT EXISTS idx_r4_runs_category ON structured_extraction_runs(category_code, subcategory_code);
CREATE INDEX IF NOT EXISTS idx_r4_runs_status_version ON structured_extraction_runs(status, extractor_version);

CREATE INDEX IF NOT EXISTS idx_r4_entities_run_id ON structured_entities(run_id);
CREATE INDEX IF NOT EXISTS idx_r4_entities_detail_id ON structured_entities(detail_id);
CREATE INDEX IF NOT EXISTS idx_r4_entities_procurement_id ON structured_entities(procurement_id);
CREATE INDEX IF NOT EXISTS idx_r4_entities_category ON structured_entities(category_code);
CREATE INDEX IF NOT EXISTS idx_r4_entities_mfr_norm ON structured_entities(manufacturer_normalized) WHERE manufacturer_normalized IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_r4_entities_brand_norm ON structured_entities(brand_normalized) WHERE brand_normalized IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_r4_entities_model_norm ON structured_entities(model_article_normalized) WHERE model_article_normalized IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_r4_entities_name_norm ON structured_entities(product_name_normalized) WHERE product_name_normalized IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_r4_attrs_entity_id ON structured_attributes(entity_id);
CREATE INDEX IF NOT EXISTS idx_r4_attrs_name_norm ON structured_attributes(attribute_name_normalized);
