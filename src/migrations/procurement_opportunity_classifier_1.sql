-- WIP=PROCUREMENT-OPPORTUNITY-CLASSIFIER-1
-- Universal procurement opportunity classifier storage.
--
-- Apply ONLY via the canonical S13 DDL admin route:
--   ssh <S13_SSH_USER>@S13
--   sudo -n -u postgres psql -d crm -v ON_ERROR_STOP=1 -f <this file>
-- Do NOT apply from Streamlit/runtime.
--
-- Additive and idempotent.  The existing computer_tz_daemon.py,
-- document pipeline and medal pipeline are not changed.

CREATE TABLE IF NOT EXISTS crm_procurement_classifications (
    object_key                  TEXT PRIMARY KEY,
    tender_id                   BIGINT,
    registry_type               TEXT,

    procurement_mode            TEXT NOT NULL,
    object_present              BOOLEAN NOT NULL DEFAULT FALSE,

    primary_class               TEXT,
    object_subcategory          TEXT,
    object_type                 TEXT,
    object_subtype              TEXT,
    work_type                   TEXT,

    classification_status       TEXT NOT NULL,
    classification_confidence   NUMERIC(5,4) NOT NULL DEFAULT 0,

    model_name                  TEXT,
    model_version               TEXT,

    source_hash                 TEXT,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE crm_procurement_classifications
    DROP CONSTRAINT IF EXISTS ck_cpc_procurement_mode;
ALTER TABLE crm_procurement_classifications
    ADD CONSTRAINT ck_cpc_procurement_mode
    CHECK (procurement_mode IN (
        'direct_supply',
        'works_with_products',
        'pure_works',
        'service',
        'unknown'
    ));

ALTER TABLE crm_procurement_classifications
    DROP CONSTRAINT IF EXISTS ck_cpc_status;
ALTER TABLE crm_procurement_classifications
    ADD CONSTRAINT ck_cpc_status
    CHECK (classification_status IN ('ready', 'needs_documents', 'error'));

CREATE INDEX IF NOT EXISTS ix_cpc_registry_tender
    ON crm_procurement_classifications (registry_type, tender_id);
CREATE INDEX IF NOT EXISTS ix_cpc_status
    ON crm_procurement_classifications (classification_status);


CREATE TABLE IF NOT EXISTS crm_procurement_opportunities (
    id                          BIGSERIAL PRIMARY KEY,

    object_key                  TEXT NOT NULL,
    tender_id                   BIGINT,
    registry_type               TEXT,

    procurement_mode            TEXT NOT NULL,

    category_code               TEXT NOT NULL,
    category_name               TEXT,

    subcategory_code            TEXT NOT NULL,
    subcategory_name            TEXT,

    product_name                TEXT NOT NULL,

    quantity                    NUMERIC,
    unit                        TEXT,

    taxonomy_action             TEXT NOT NULL,
    confidence                  NUMERIC(5,4) NOT NULL DEFAULT 0,

    repeat_signature            TEXT,

    model_name                  TEXT,
    model_version               TEXT,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (object_key, category_code, subcategory_code, product_name)
);

ALTER TABLE crm_procurement_opportunities
    DROP CONSTRAINT IF EXISTS ck_cpo_procurement_mode;
ALTER TABLE crm_procurement_opportunities
    ADD CONSTRAINT ck_cpo_procurement_mode
    CHECK (procurement_mode IN (
        'direct_supply',
        'works_with_products',
        'pure_works',
        'service',
        'unknown'
    ));

ALTER TABLE crm_procurement_opportunities
    DROP CONSTRAINT IF EXISTS ck_cpo_taxonomy_action;
ALTER TABLE crm_procurement_opportunities
    ADD CONSTRAINT ck_cpo_taxonomy_action
    CHECK (taxonomy_action IN ('existing', 'propose_new'));

CREATE INDEX IF NOT EXISTS ix_cpo_object_key
    ON crm_procurement_opportunities (object_key);
CREATE INDEX IF NOT EXISTS ix_cpo_category_subcategory
    ON crm_procurement_opportunities (category_code, subcategory_code);
CREATE INDEX IF NOT EXISTS ix_cpo_repeat_signature
    ON crm_procurement_opportunities (repeat_signature);
CREATE INDEX IF NOT EXISTS ix_cpo_registry_tender
    ON crm_procurement_opportunities (registry_type, tender_id);


CREATE TABLE IF NOT EXISTS crm_product_taxonomy_discovery (
    id                          BIGSERIAL PRIMARY KEY,

    parent_name                 TEXT NOT NULL,
    parent_name_norm            TEXT NOT NULL,

    subcategory_name            TEXT NOT NULL,
    subcategory_name_norm       TEXT NOT NULL,

    sample_product_name         TEXT,

    procurement_count           INTEGER NOT NULL DEFAULT 0,
    total_amount                NUMERIC NOT NULL DEFAULT 0,
    confidence_sum              NUMERIC NOT NULL DEFAULT 0,

    status                      TEXT NOT NULL DEFAULT 'candidate',

    first_seen_at               TIMESTAMPTZ,
    last_seen_at                TIMESTAMPTZ,
    promoted_at                 TIMESTAMPTZ,

    UNIQUE (parent_name_norm, subcategory_name_norm)
);

ALTER TABLE crm_product_taxonomy_discovery
    DROP CONSTRAINT IF EXISTS ck_cptd_status;
ALTER TABLE crm_product_taxonomy_discovery
    ADD CONSTRAINT ck_cptd_status
    CHECK (status IN ('candidate', 'promoted'));

CREATE INDEX IF NOT EXISTS ix_cptd_status
    ON crm_product_taxonomy_discovery (status);


GRANT SELECT, INSERT, UPDATE, DELETE ON crm_procurement_classifications TO crm_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON crm_procurement_opportunities TO crm_app;
GRANT USAGE, SELECT ON SEQUENCE crm_procurement_opportunities_id_seq TO crm_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON crm_product_taxonomy_discovery TO crm_app;
GRANT USAGE, SELECT ON SEQUENCE crm_product_taxonomy_discovery_id_seq TO crm_app;
