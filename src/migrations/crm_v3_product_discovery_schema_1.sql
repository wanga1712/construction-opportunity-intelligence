-- Migration: crm_v3_product_discovery_schema_1.sql
-- Purpose: Schema for product categories, observations, relations, and normalization cache in TEST DB.
-- Notes: OFFLINE/TEST_DB only. Not applied to production DB.

CREATE TABLE IF NOT EXISTS product_categories (
    category_id VARCHAR(64) PRIMARY KEY,
    parent_id VARCHAR(64) REFERENCES product_categories(category_id) ON DELETE SET NULL,
    level VARCHAR(32) NOT NULL DEFAULT 'CATEGORY', -- DOMAIN, CATEGORY, SUBCATEGORY, PRODUCT_FAMILY
    domain VARCHAR(64) NOT NULL DEFAULT 'GENERAL',
    canonical_name VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'AUTO_DISCOVERED', -- AUTO_DISCOVERED, MODEL_CONFIRMED, EXPERT_CONFIRMED, REJECTED, MERGED
    model_confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    created_from_observation_id VARCHAR(64),
    observation_count INTEGER NOT NULL DEFAULT 0,
    procurement_count INTEGER NOT NULL DEFAULT 0,
    distinct_customer_count INTEGER NOT NULL DEFAULT 0,
    region_count INTEGER NOT NULL DEFAULT 0,
    total_observed_product_value DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    median_observation_value DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    merged_into_id VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_product_categories_parent ON product_categories(parent_id);
CREATE INDEX IF NOT EXISTS idx_product_categories_status ON product_categories(status);
CREATE INDEX IF NOT EXISTS idx_product_categories_name ON product_categories(canonical_name);

CREATE TABLE IF NOT EXISTS product_category_aliases (
    id SERIAL PRIMARY KEY,
    alias VARCHAR(255) NOT NULL UNIQUE,
    category_id VARCHAR(64) NOT NULL REFERENCES product_categories(category_id) ON DELETE CASCADE,
    source VARCHAR(64) NOT NULL DEFAULT 'AUTO_DISCOVERY',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.8,
    first_observation_id VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_product_aliases_cat ON product_category_aliases(category_id);
CREATE INDEX IF NOT EXISTS idx_product_aliases_text ON product_category_aliases(alias);

CREATE TABLE IF NOT EXISTS product_observations (
    observation_id VARCHAR(64) PRIMARY KEY,
    observation_key VARCHAR(64) NOT NULL UNIQUE,
    procurement_id BIGINT NOT NULL,
    opportunity_id BIGINT,
    document_id VARCHAR(128),
    document_hash VARCHAR(64),
    document_version INTEGER NOT NULL DEFAULT 1,
    sheet_name VARCHAR(128) NOT NULL DEFAULT '',
    page_number INTEGER,
    table_id VARCHAR(64) NOT NULL DEFAULT '',
    section_name VARCHAR(255) NOT NULL DEFAULT '',
    subsection_name VARCHAR(255) NOT NULL DEFAULT '',
    row_index INTEGER NOT NULL DEFAULT 0,
    raw_name TEXT NOT NULL DEFAULT '',
    normalized_product_name VARCHAR(255) NOT NULL DEFAULT '',
    row_type VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN',
    unit_raw VARCHAR(64) NOT NULL DEFAULT '',
    unit_normalized VARCHAR(32) NOT NULL DEFAULT 'OTHER',
    quantity DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    unit_price DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    total_amount DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    currency VARCHAR(16) NOT NULL DEFAULT 'RUB',
    classification_confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    normalization_confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    category_confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    category_id VARCHAR(64) REFERENCES product_categories(category_id) ON DELETE SET NULL,
    subcategory_id VARCHAR(64) REFERENCES product_categories(category_id) ON DELETE SET NULL,
    seed_observation_id VARCHAR(64),
    discovery_method VARCHAR(64) NOT NULL DEFAULT 'SEEDLESS',
    commercial_significance_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    source_cells_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_fragment TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    superseded_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_product_observations_pid ON product_observations(procurement_id);
CREATE INDEX IF NOT EXISTS idx_product_observations_cat ON product_observations(category_id);
CREATE INDEX IF NOT EXISTS idx_product_observations_key ON product_observations(observation_key);

CREATE TABLE IF NOT EXISTS product_category_relations (
    relation_id VARCHAR(64) PRIMARY KEY,
    category_a_id VARCHAR(64) NOT NULL REFERENCES product_categories(category_id) ON DELETE CASCADE,
    category_b_id VARCHAR(64) NOT NULL REFERENCES product_categories(category_id) ON DELETE CASCADE,
    same_section_count INTEGER NOT NULL DEFAULT 0,
    same_document_count INTEGER NOT NULL DEFAULT 0,
    same_procurement_count INTEGER NOT NULL DEFAULT 0,
    conditional_probability_b_given_a DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    conditional_probability_a_given_b DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    median_amount_ratio DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    median_quantity_similarity DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(category_a_id, category_b_id)
);

CREATE TABLE IF NOT EXISTS product_normalizer_cache (
    cache_key VARCHAR(64) PRIMARY KEY,
    input_hash VARCHAR(64) NOT NULL,
    model_name VARCHAR(64) NOT NULL,
    model_version VARCHAR(32) NOT NULL,
    prompt_version VARCHAR(32) NOT NULL,
    row_context_json JSONB NOT NULL,
    decision_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
