-- COMMERCIAL-ROUTING-V3-CORE-IMPLEMENTATION-1 schema

-- Global category↔OKPD priors (user-independent runtime)
CREATE TABLE IF NOT EXISTS crm_category_okpd_priors (
    id BIGSERIAL PRIMARY KEY,
    commercial_category_code TEXT NOT NULL,
    okpd_pattern TEXT NOT NULL,
    match_type TEXT NOT NULL DEFAULT 'PREFIX',
    prior_weight NUMERIC NOT NULL DEFAULT 50,
    signal_role TEXT NOT NULL DEFAULT 'CANDIDATE_SIGNAL',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    provenance TEXT NOT NULL DEFAULT 'seed',
    source_table TEXT,
    source_row_id BIGINT,
    source_user_id TEXT,
    migration_class TEXT,
    registry_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (commercial_category_code, okpd_pattern, match_type)
);

CREATE INDEX IF NOT EXISTS idx_okpd_priors_pattern ON crm_category_okpd_priors (okpd_pattern, active);

-- Category-centric routing signals (NOT document matcher stop phrases)
CREATE TABLE IF NOT EXISTS crm_category_routing_signals (
    id BIGSERIAL PRIMARY KEY,
    commercial_category_code TEXT,
    signal_type TEXT NOT NULL,
    signal_scope TEXT NOT NULL DEFAULT 'PRELIMINARY_TITLE',
    phrase TEXT NOT NULL,
    signal_strength TEXT NOT NULL DEFAULT 'LEGACY_SOFT_NEGATIVE_DEFAULT',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    provenance TEXT NOT NULL DEFAULT 'seed',
    source_table TEXT,
    source_row_id BIGINT,
    migration_class TEXT,
    registry_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_routing_signals_cat ON crm_category_routing_signals (commercial_category_code, active);

-- Canonical category-level opportunity storage
CREATE TABLE IF NOT EXISTS crm_procurement_category_opportunities (
    id BIGSERIAL PRIMARY KEY,
    procurement_id BIGINT NOT NULL,
    assessment_id BIGINT,
    commercial_category_code TEXT NOT NULL,
    commercial_subcategory_code TEXT,
    opportunity_track TEXT NOT NULL,

    -- S13-only commercial opportunity lifecycle derived from S7 source lifecycle.
    -- S7 stage is not mirrored as-is; it is normalized into business-level events.
    commercial_state TEXT NOT NULL DEFAULT 'ACTIVE',
    last_source_event TEXT NOT NULL DEFAULT 'OPEN',
    last_source_seen_at TIMESTAMPTZ,
    source_missing_since TIMESTAMPTZ,
    source_sync_status TEXT NOT NULL DEFAULT 'OK',

    source_contour TEXT NOT NULL,
    procurement_form TEXT NOT NULL,
    analysis_mode TEXT NOT NULL,
    category_confidence NUMERIC NOT NULL DEFAULT 0,
    research_action TEXT NOT NULL,
    research_priority INTEGER NOT NULL DEFAULT 0,
    research_value_score INTEGER NOT NULL DEFAULT 0,
    commercial_priority_score INTEGER NOT NULL DEFAULT 0,
    candidate_medal TEXT NOT NULL,
    expected_category_value NUMERIC,
    category_value_basis TEXT NOT NULL,
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    positive_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    negative_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    registry_version INTEGER,
    registry_hash TEXT,
    prompt_version TEXT,
    routing_version TEXT NOT NULL DEFAULT 'v3',
    model_name TEXT,
    status TEXT NOT NULL DEFAULT 'CURRENT',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (procurement_id, commercial_category_code, commercial_subcategory_code, opportunity_track, routing_version)
);

CREATE INDEX IF NOT EXISTS idx_cat_opps_procurement ON crm_procurement_category_opportunities (procurement_id, status);

-- Transition audit: no silent state mutations.
CREATE TABLE IF NOT EXISTS crm_category_opportunity_lifecycle_audit (
    id BIGSERIAL PRIMARY KEY,
    procurement_id BIGINT NOT NULL,
    opportunity_id BIGINT,
    commercial_category_code TEXT NOT NULL,
    commercial_subcategory_code TEXT,
    opportunity_track TEXT NOT NULL,

    old_source_event TEXT,
    new_source_event TEXT,

    old_commercial_state TEXT,
    new_commercial_state TEXT,

    reason TEXT NOT NULL,

    source_seen_at TIMESTAMPTZ,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    routing_version TEXT NOT NULL DEFAULT 'v3',
    registry_version INTEGER,
    registry_hash TEXT
);

CREATE INDEX IF NOT EXISTS idx_cat_opps_lifecycle_audit_proc
    ON crm_category_opportunity_lifecycle_audit (procurement_id, changed_at DESC);

-- Legacy expert knowledge audit (S7 migration provenance)
CREATE TABLE IF NOT EXISTS crm_legacy_okpd_migration_audit (
    id BIGSERIAL PRIMARY KEY,
    source_table TEXT NOT NULL,
    source_row_id BIGINT,
    source_user_id TEXT,
    okpd_pattern TEXT,
    commercial_category_code TEXT,
    migration_class TEXT NOT NULL,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
