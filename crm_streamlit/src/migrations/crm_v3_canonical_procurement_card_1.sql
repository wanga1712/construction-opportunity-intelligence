-- CRM-V3 canonical procurement card / prior semantics
-- No runtime DDL. Apply via migration runner.

ALTER TABLE crm_category_okpd_priors
    ADD COLUMN IF NOT EXISTS prior_kind TEXT;

COMMENT ON COLUMN crm_category_okpd_priors.prior_kind IS
    'COMMERCIAL_PRODUCT_PRIOR | CONTEXTUAL_RESEARCH_PRIOR';

-- Critical: 27.32 cable/wire is contextual for tray/support categories, not direct product.
UPDATE crm_category_okpd_priors
   SET prior_kind = 'CONTEXTUAL_RESEARCH_PRIOR',
       signal_role = 'CONTEXTUAL_RESEARCH'
 WHERE commercial_category_code IN ('cable_support_systems', 'composite_cable_trays')
   AND (
        okpd_pattern = '27.32'
        OR okpd_pattern LIKE '27.32.%'
        OR okpd_pattern = '27.3'
        OR okpd_pattern LIKE '27.3.%'
   );

-- Default remaining active priors to commercial product unless already set.
UPDATE crm_category_okpd_priors
   SET prior_kind = 'COMMERCIAL_PRODUCT_PRIOR'
 WHERE active = TRUE
   AND prior_kind IS NULL;

-- Snapshot cache for canonical pre-model cards (S13 only).
CREATE TABLE IF NOT EXISTS crm_v3_canonical_procurement_cards (
    procurement_id BIGINT PRIMARY KEY REFERENCES crm_procurements(id),
    card_json JSONB NOT NULL,
    card_version TEXT NOT NULL DEFAULT 'V1',
    source_fingerprint TEXT,
    built_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_crm_v3_canonical_cards_updated
    ON crm_v3_canonical_procurement_cards (updated_at DESC);
