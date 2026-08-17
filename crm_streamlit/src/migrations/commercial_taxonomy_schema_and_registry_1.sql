-- COMMERCIAL-TAXONOMY-SCHEMA-AND-REGISTRY-1
-- Formal migration only. Apply manually on CRM DB; no runtime auto-DDL.

-- ─── 1. Extend crm_product_categories ───────────────────────────────────────
ALTER TABLE crm_product_categories
    ADD COLUMN IF NOT EXISTS semantic_type TEXT NOT NULL DEFAULT 'COMMERCIAL_CATEGORY',
    ADD COLUMN IF NOT EXISTS lifecycle_state TEXT NOT NULL DEFAULT 'ACTIVE',
    ADD COLUMN IF NOT EXISTS searchability_mode TEXT NOT NULL DEFAULT 'DIRECT_SEARCHABLE',
    ADD COLUMN IF NOT EXISTS legacy_compat_role TEXT;

-- ─── 2. Extend crm_product_subcategories ────────────────────────────────────
ALTER TABLE crm_product_subcategories
    ADD COLUMN IF NOT EXISTS semantic_type TEXT NOT NULL DEFAULT 'COMMERCIAL_SUBCATEGORY',
    ADD COLUMN IF NOT EXISTS searchability_mode TEXT NOT NULL DEFAULT 'DIRECT_SEARCHABLE';

-- ─── 3. Extend crm_product_subcategory_terms ────────────────────────────────
ALTER TABLE crm_product_subcategory_terms
    ADD COLUMN IF NOT EXISTS term_semantic_type TEXT,
    ADD COLUMN IF NOT EXISTS evidence_role TEXT;

-- ─── 4. Non-commercial taxonomy dimensions ──────────────────────────────────
CREATE TABLE IF NOT EXISTS crm_taxonomy_dimensions (
    id BIGSERIAL PRIMARY KEY,
    dimension_type TEXT NOT NULL,
    dimension_code TEXT NOT NULL,
    display_name TEXT NOT NULL,
    normalized_term TEXT NOT NULL,
    term_semantic_type TEXT NOT NULL,
    evidence_role TEXT NOT NULL DEFAULT 'SIGNAL_ONLY',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    registry_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (dimension_type, dimension_code)
);

CREATE INDEX IF NOT EXISTS idx_taxonomy_dimensions_type_active
    ON crm_taxonomy_dimensions (dimension_type, is_active);

CREATE INDEX IF NOT EXISTS idx_taxonomy_dimensions_normalized_term
    ON crm_taxonomy_dimensions (normalized_term);

-- ─── 5. Legacy 14-code compatibility mapping ────────────────────────────────
CREATE TABLE IF NOT EXISTS crm_category_legacy_compat (
    id BIGSERIAL PRIMARY KEY,
    legacy_category_code TEXT NOT NULL UNIQUE,
    commercial_category_code TEXT,
    commercial_subcategory_code TEXT,
    material_family_code TEXT,
    object_context_code TEXT,
    application_area_code TEXT,
    work_method_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    compat_strategy TEXT NOT NULL,
    notes TEXT,
    registry_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_category_legacy_compat_strategy
    ON crm_category_legacy_compat (compat_strategy);

-- ─── 6. Commercial signal examples (reference / regression fixtures) ────────
CREATE TABLE IF NOT EXISTS crm_taxonomy_signal_examples (
    id BIGSERIAL PRIMARY KEY,
    example_term TEXT NOT NULL,
    normalized_term TEXT NOT NULL,
    term_semantic_type TEXT NOT NULL,
    evidence_role TEXT NOT NULL,
    dimension_type TEXT,
    dimension_code TEXT,
    commercial_category_code TEXT,
    commercial_subcategory_code TEXT,
    is_commercial_category BOOLEAN NOT NULL DEFAULT FALSE,
    notes TEXT,
    registry_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (normalized_term, term_semantic_type)
);
