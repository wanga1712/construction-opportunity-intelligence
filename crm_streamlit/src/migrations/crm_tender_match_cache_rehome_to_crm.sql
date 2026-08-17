-- S7-SOURCE-READONLY-ENFORCEMENT-AND-MATCH-CACHE-REHOME-1
-- Apply ONLY to current CRM DB (10.8.0.7:5432/crm). Never to tender_monitor.
-- Creates CRM-owned crm_tender_match_cache. Data copy is performed by controlled script.

CREATE TABLE IF NOT EXISTS crm_tender_match_cache (
    id               SERIAL PRIMARY KEY,
    source_table     TEXT NOT NULL,
    source_id        INTEGER NOT NULL,
    crm_profile_id   INTEGER NOT NULL,
    match_score      INTEGER NOT NULL DEFAULT 0,
    matched_keywords TEXT[],
    matched_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_table, source_id, crm_profile_id)
);

CREATE INDEX IF NOT EXISTS idx_crm_match_profile
    ON crm_tender_match_cache (crm_profile_id);
CREATE INDEX IF NOT EXISTS idx_crm_match_score
    ON crm_tender_match_cache (match_score DESC);
CREATE INDEX IF NOT EXISTS idx_crm_match_source
    ON crm_tender_match_cache (source_table, source_id);

COMMENT ON TABLE crm_tender_match_cache IS
  'CRM derived match cache. Owner=crm_db. Legacy copy may remain on tender_monitor until cleanup.';
