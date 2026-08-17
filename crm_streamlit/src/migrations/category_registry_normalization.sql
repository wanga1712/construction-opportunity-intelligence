-- CATEGORY-REGISTRY-NORMALIZATION-1: DB Migration
-- Extends crm_product_categories with full category contract fields
-- Adds versioning table

-- 1. Extend crm_product_categories
ALTER TABLE crm_product_categories
    ADD COLUMN IF NOT EXISTS description TEXT,
    ADD COLUMN IF NOT EXISTS aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS positive_signals JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS negative_contexts JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS applicable_routes JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS applicable_object_types JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS applicable_procurement_types JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS default_role TEXT NOT NULL DEFAULT 'EMBEDDED_MATERIAL',
    ADD COLUMN IF NOT EXISTS allowed_roles JSONB NOT NULL DEFAULT '["PRIMARY_SUPPLY","EMBEDDED_MATERIAL"]'::jsonb,
    ADD COLUMN IF NOT EXISTS commercial_entry_points JSONB NOT NULL DEFAULT '["DIRECT_SUPPLY"]'::jsonb,
    ADD COLUMN IF NOT EXISTS document_search_plan JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS section_search_plan JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS extraction_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS registry_version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS updated_by TEXT NOT NULL DEFAULT 'system';

-- 2. Registry versions table (global audit log of registry changes)
CREATE TABLE IF NOT EXISTS crm_category_registry_versions (
    id SERIAL PRIMARY KEY,
    version INTEGER NOT NULL,
    registry_hash TEXT NOT NULL,
    change_description TEXT,
    changed_by TEXT NOT NULL DEFAULT 'system',
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    affected_category_codes JSONB DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_cat_reg_ver_version ON crm_category_registry_versions(version DESC);

-- 3. CRM settings key for global registry version
INSERT INTO crm_settings(key, value) VALUES ('category_registry_version', '1')
ON CONFLICT (key) DO NOTHING;

INSERT INTO crm_settings(key, value) VALUES ('category_registry_hash', '')
ON CONFLICT (key) DO NOTHING;

-- 4. Backfill initial registry_version = 1 for all existing categories
UPDATE crm_product_categories SET registry_version = 1 WHERE registry_version IS NULL OR registry_version < 1;
