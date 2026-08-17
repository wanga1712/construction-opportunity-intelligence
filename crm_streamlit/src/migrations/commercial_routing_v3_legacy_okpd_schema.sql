-- COMMERCIAL-ROUTING-V3-LEGACY-OKPD-CATEGORY-KNOWLEDGE-1 schema extensions

ALTER TABLE crm_category_okpd_priors
    ADD COLUMN IF NOT EXISTS signal_role TEXT NOT NULL DEFAULT 'CANDIDATE_SIGNAL';

ALTER TABLE crm_category_routing_signals
    ADD COLUMN IF NOT EXISTS signal_strength TEXT NOT NULL DEFAULT 'LEGACY_SOFT_NEGATIVE_DEFAULT';

ALTER TABLE crm_legacy_okpd_migration_audit
    ADD COLUMN IF NOT EXISTS source_profile_id TEXT,
    ADD COLUMN IF NOT EXISTS legacy_category TEXT,
    ADD COLUMN IF NOT EXISTS classification TEXT,
    ADD COLUMN IF NOT EXISTS target_category_code TEXT,
    ADD COLUMN IF NOT EXISTS target_signal_role TEXT,
    ADD COLUMN IF NOT EXISTS migration_status TEXT,
    ADD COLUMN IF NOT EXISTS review_reason TEXT;

-- Generated legacy audit rows use classification/migration_status; migration_class is legacy NOT NULL.
ALTER TABLE crm_legacy_okpd_migration_audit
    ALTER COLUMN migration_class DROP NOT NULL;
ALTER TABLE crm_legacy_okpd_migration_audit
    ALTER COLUMN migration_class SET DEFAULT 'AUDIT_ONLY';
