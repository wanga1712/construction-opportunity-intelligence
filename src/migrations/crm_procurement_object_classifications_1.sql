-- WIP=CANONICAL-OBJECT-LAYER-PRODUCTION-V1
-- Canonical production Object Layer: PROCUREMENT -> PROCUREMENT_MODE -> OBJECT.
--
-- Apply ONLY via the canonical S13 DDL admin route:
--   ssh <S13_SSH_USER>@S13
--   sudo -n -u postgres psql -d crm -v ON_ERROR_STOP=1 -f <this file>
-- Do NOT apply from Streamlit/runtime.  No medals.  No product candidates.
--
-- Additive + idempotent: safe to apply twice.  No existing table is altered.
--
-- Vocabulary is owned by src/services/expert_object_taxonomy.py; classification
-- contract is owned by src/services/object_classification.py.  The DB keeps
-- only cheap guards so no free-text label or guess can land here.

CREATE TABLE IF NOT EXISTS crm_procurement_object_classifications (
    id                          BIGSERIAL PRIMARY KEY,
    procurement_id              INTEGER NOT NULL REFERENCES crm_procurements(id) ON DELETE CASCADE,
    procurement_mode            TEXT NOT NULL,
    object_applicable           BOOLEAN NOT NULL,
    object_sector               TEXT,
    object_type                 TEXT,
    object_subtype              TEXT,
    object_context              TEXT,
    application_area            TEXT,
    classification_status       TEXT NOT NULL,
    classification_source       TEXT NOT NULL,
    classification_method       TEXT NOT NULL,
    confidence                  NUMERIC(5, 4) NOT NULL DEFAULT 0,
    confidence_class            TEXT NOT NULL,
    classification_version      TEXT NOT NULL,
    matched_terms               JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_current                  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE crm_procurement_object_classifications
    DROP CONSTRAINT IF EXISTS ck_cpoc_status;
ALTER TABLE crm_procurement_object_classifications
    ADD CONSTRAINT ck_cpoc_status
    CHECK (classification_status IN (
        'RESOLVED_REVIEWED',
        'RESOLVED_HIGH_CONFIDENCE',
        'DIRECT_NA',
        'SERVICE_NA',
        'AMBIGUOUS',
        'OBJECT_MISSING',
        'OBJECT_CONFLICT',
        'OBJECT_NONCANONICAL'
    ));

ALTER TABLE crm_procurement_object_classifications
    DROP CONSTRAINT IF EXISTS ck_cpoc_source;
ALTER TABLE crm_procurement_object_classifications
    ADD CONSTRAINT ck_cpoc_source
    CHECK (classification_source IN (
        'EXPERT_CONFIRMED',
        'REVIEWED',
        'DETERMINISTIC_HIGH_CONFIDENCE',
        'CANONICAL_CURRENT',
        'UNRESOLVED'
    ));

ALTER TABLE crm_procurement_object_classifications
    DROP CONSTRAINT IF EXISTS ck_cpoc_mode;
ALTER TABLE crm_procurement_object_classifications
    ADD CONSTRAINT ck_cpoc_mode
    CHECK (procurement_mode IN ('DIRECT', 'OBJECT', 'SERVICE_NO_OBJECT', 'AMBIGUOUS'));

ALTER TABLE crm_procurement_object_classifications
    DROP CONSTRAINT IF EXISTS ck_cpoc_confidence_class;
ALTER TABLE crm_procurement_object_classifications
    ADD CONSTRAINT ck_cpoc_confidence_class
    CHECK (confidence_class IN ('EXPERT', 'HIGH', 'NONE'));

-- object_applicable is exactly the "resolved" state; no partially applied row.
ALTER TABLE crm_procurement_object_classifications
    DROP CONSTRAINT IF EXISTS ck_cpoc_applicable;
ALTER TABLE crm_procurement_object_classifications
    ADD CONSTRAINT ck_cpoc_applicable
    CHECK (
        object_applicable
        = (classification_status IN ('RESOLVED_REVIEWED', 'RESOLVED_HIGH_CONFIDENCE'))
    );

-- DIRECT / SERVICE have no object lifecycle: all three axes are the N/A sentinel.
ALTER TABLE crm_procurement_object_classifications
    DROP CONSTRAINT IF EXISTS ck_cpoc_na_axes;
ALTER TABLE crm_procurement_object_classifications
    ADD CONSTRAINT ck_cpoc_na_axes
    CHECK (
        classification_status NOT IN ('DIRECT_NA', 'SERVICE_NA')
        OR (object_sector = 'N/A' AND object_type = 'N/A' AND object_subtype = 'N/A')
    );

-- No unresolved status may carry an OBJECT_TYPE.  UNKNOWN stays UNKNOWN.
ALTER TABLE crm_procurement_object_classifications
    DROP CONSTRAINT IF EXISTS ck_cpoc_unresolved_axes;
ALTER TABLE crm_procurement_object_classifications
    ADD CONSTRAINT ck_cpoc_unresolved_axes
    CHECK (
        classification_status NOT IN (
            'AMBIGUOUS', 'OBJECT_MISSING', 'OBJECT_CONFLICT', 'OBJECT_NONCANONICAL'
        )
        OR object_type IS NULL
    );

-- One current object row per procurement per classification version.
CREATE UNIQUE INDEX IF NOT EXISTS uix_cpoc_procurement_version
    ON crm_procurement_object_classifications (procurement_id, classification_version);

CREATE INDEX IF NOT EXISTS idx_cpoc_object
    ON crm_procurement_object_classifications (object_sector, object_type, object_subtype);

CREATE INDEX IF NOT EXISTS idx_cpoc_status
    ON crm_procurement_object_classifications (classification_status);

CREATE INDEX IF NOT EXISTS idx_cpoc_version
    ON crm_procurement_object_classifications (classification_version, is_current);

GRANT SELECT, INSERT, UPDATE, DELETE ON crm_procurement_object_classifications TO crm_app;
GRANT USAGE, SELECT ON SEQUENCE crm_procurement_object_classifications_id_seq TO crm_app;