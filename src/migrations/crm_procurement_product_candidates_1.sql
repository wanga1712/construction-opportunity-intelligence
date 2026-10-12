-- WIP=PRODUCT-CANDIDATE-LAYER-PRODUCTION-V1
-- Layer 1 storage: OBJECT -> PRODUCT candidates (PRE_EVIDENCE).
--
-- Apply ONLY via the canonical S13 DDL admin route:
--   ssh <S13_SSH_USER>@S13
--   sudo -n -u postgres psql -d crm -v ON_ERROR_STOP=1 -f <this file>
-- Do NOT apply from Streamlit/runtime. No medals. No category opportunities.
--
-- Additive + idempotent: safe to apply twice. No existing table is altered.

CREATE TABLE IF NOT EXISTS crm_procurement_product_candidates (
    id                  BIGSERIAL PRIMARY KEY,
    procurement_id      INTEGER NOT NULL REFERENCES crm_procurements(id) ON DELETE CASCADE,
    procurement_mode    TEXT NOT NULL,
    object_sector       TEXT,
    object_type         TEXT,
    object_subtype      TEXT,
    object_context      TEXT,
    product_family      TEXT NOT NULL,
    product_type        TEXT NOT NULL,
    application         TEXT,
    material            TEXT,
    variant             TEXT,
    technology          TEXT,
    applicability       TEXT NOT NULL,
    candidate_status    TEXT NOT NULL,
    candidate_source    TEXT NOT NULL,
    candidate_version   TEXT NOT NULL,
    is_current          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Canonical vocabularies are owned by src/services/product_ontology.py.
-- The DB keeps only cheap guards so no medal/opportunity text can ever land here.
ALTER TABLE crm_procurement_product_candidates
    DROP CONSTRAINT IF EXISTS ck_cppc_applicability;
ALTER TABLE crm_procurement_product_candidates
    ADD CONSTRAINT ck_cppc_applicability
    CHECK (applicability IN ('YES', 'CONDITIONAL', 'NO', 'UNKNOWN'));

ALTER TABLE crm_procurement_product_candidates
    DROP CONSTRAINT IF EXISTS ck_cppc_candidate_status;
ALTER TABLE crm_procurement_product_candidates
    ADD CONSTRAINT ck_cppc_candidate_status
    CHECK (candidate_status = 'PRE_EVIDENCE');

ALTER TABLE crm_procurement_product_candidates
    DROP CONSTRAINT IF EXISTS ck_cppc_mode;
ALTER TABLE crm_procurement_product_candidates
    ADD CONSTRAINT ck_cppc_mode
    CHECK (procurement_mode IN ('DIRECT', 'OBJECT', 'SERVICE_NO_OBJECT', 'AMBIGUOUS'));

-- Layer 1 has no medal / opportunity column at all; TECHNOLOGY is schema-ready
-- but the canonical registry is empty, so only NULL is accepted for now.
ALTER TABLE crm_procurement_product_candidates
    DROP CONSTRAINT IF EXISTS ck_cppc_technology_unset;
ALTER TABLE crm_procurement_product_candidates
    ADD CONSTRAINT ck_cppc_technology_unset
    CHECK (technology IS NULL OR technology = '');

-- Idempotency key: one row per (procurement, model version, canonical product axes,
-- object axes). NULLS NOT DISTINCT so absent application/material/variant/subtype
-- still collide and upsert instead of duplicating.
CREATE UNIQUE INDEX IF NOT EXISTS uix_cppc_identity
    ON crm_procurement_product_candidates (
        procurement_id,
        candidate_version,
        product_family,
        product_type,
        application,
        material,
        variant,
        object_sector,
        object_type,
        object_subtype
    ) NULLS NOT DISTINCT;

CREATE INDEX IF NOT EXISTS idx_cppc_procurement_current
    ON crm_procurement_product_candidates (procurement_id, is_current);

CREATE INDEX IF NOT EXISTS idx_cppc_version
    ON crm_procurement_product_candidates (candidate_version);

CREATE INDEX IF NOT EXISTS idx_cppc_product
    ON crm_procurement_product_candidates (product_family, product_type);

GRANT SELECT, INSERT, UPDATE, DELETE ON crm_procurement_product_candidates TO crm_app;
GRANT USAGE, SELECT ON SEQUENCE crm_procurement_product_candidates_id_seq TO crm_app;