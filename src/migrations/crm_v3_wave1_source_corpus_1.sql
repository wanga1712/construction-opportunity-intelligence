-- CRM-V3-WAVE1-SOURCE-CORPUS-INGEST-AND-OKPD-DISTRIBUTION-1
-- S13 CRM only. Controlled migration. NO runtime auto-DDL.

CREATE TABLE IF NOT EXISTS crm_v3_wave1_generations (
    generation_id   BIGSERIAL PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'BUILDING'
        CHECK (status IN ('BUILDING', 'COMPLETE', 'FAILED')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    report_json     JSONB,
    error_summary   TEXT
);

CREATE TABLE IF NOT EXISTS crm_v3_source_corpus (
    id                    BIGSERIAL PRIMARY KEY,
    identity_key          TEXT NOT NULL,
    source_contour        TEXT NOT NULL,
    contract_number       TEXT,
    source_table          TEXT NOT NULL,
    source_id             BIGINT NOT NULL,
    law_type              TEXT NOT NULL,
    normalized_lifecycle  TEXT NOT NULL,
    integrity_class       TEXT NOT NULL,
    pre_routing_state     TEXT NOT NULL,
    auction_name          TEXT,
    okpd_id               BIGINT,
    okpd_code             TEXT,
    okpd_name             TEXT,
    okpd_root             TEXT,
    okpd_parent           TEXT,
    okpd_hierarchy        JSONB,
    prior_categories      JSONB,
    prior_link_count      INTEGER NOT NULL DEFAULT 0,
    business_okpd_bucket  TEXT,
    crm_procurement_id    INTEGER,
    end_date              DATE,
    source_created_at     TIMESTAMPTZ,
    source_updated_at     TIMESTAMPTZ,
    discovery_class       TEXT,
    wave1_generation_id   BIGINT REFERENCES crm_v3_wave1_generations(generation_id),
    refreshed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (identity_key)
);

CREATE INDEX IF NOT EXISTS idx_crm_v3_source_corpus_lifecycle
    ON crm_v3_source_corpus (normalized_lifecycle);
CREATE INDEX IF NOT EXISTS idx_crm_v3_source_corpus_integrity
    ON crm_v3_source_corpus (integrity_class);
CREATE INDEX IF NOT EXISTS idx_crm_v3_source_corpus_okpd
    ON crm_v3_source_corpus (okpd_code);
CREATE INDEX IF NOT EXISTS idx_crm_v3_source_corpus_crm_id
    ON crm_v3_source_corpus (crm_procurement_id);
