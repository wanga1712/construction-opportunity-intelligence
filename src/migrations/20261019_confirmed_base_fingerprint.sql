-- CONFIRMED_BASE_COHORT_STABILITY_V1
-- Per-opportunity fingerprint of confirmed_category_facts. write_confirmed_base
-- recomputes only opportunities whose facts changed; untouched cards keep their
-- existing score/medal, so a new SECTION_CONFIRMED fact cannot move neighbours.

SET LOCAL lock_timeout = '15s';

CREATE TABLE IF NOT EXISTS crm_confirmed_base_fingerprint (
    opportunity_id    BIGINT PRIMARY KEY
                      REFERENCES crm_procurement_category_opportunities(id) ON DELETE CASCADE,
    facts_fingerprint TEXT NOT NULL,
    facts_count       INTEGER NOT NULL DEFAULT 0,
    value_rows        INTEGER NOT NULL DEFAULT 0,
    value_sum         NUMERIC(20,6) NOT NULL DEFAULT 0,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cbf_updated_at
    ON crm_confirmed_base_fingerprint(updated_at);
