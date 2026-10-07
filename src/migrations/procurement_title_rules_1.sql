-- APPROVED EXACT TITLE RULES V1
-- Deterministic, human-approved procurement-title -> subcategory rules.
--
-- Additive and idempotent. NO DELETEs, NO backfill here (DML is done by
-- scripts/import_approved_title_rules.py). Apply as owner role crm_app
-- (owner of the product taxonomy tables).
--
-- Runtime match key is (normalization_version, normalized_title,
-- current_category_code). A single title_group_id is NOT used as the runtime
-- key: identical construction-work titles legitimately appear in several
-- categories at once, so rules must be category-scoped and fail-safe.

BEGIN;

-- Fail fast instead of queueing behind long-lived readers on the live contour.
SET LOCAL lock_timeout = '10s';

CREATE TABLE IF NOT EXISTS crm_procurement_title_rules (
    id                    BIGSERIAL PRIMARY KEY,

    normalization_version TEXT NOT NULL,
    normalized_title      TEXT NOT NULL,

    current_category_code TEXT NOT NULL,

    action                TEXT NOT NULL,

    target_category_code  TEXT,
    target_subcategory_code TEXT,

    confidence            NUMERIC(5,4) NOT NULL,

    rule_scope            TEXT NOT NULL,
    rule_level            TEXT,

    source_title_group_id    TEXT,
    source_category_group_id TEXT,

    reason                TEXT,

    approved_source       TEXT NOT NULL,
    execution_enabled     BOOLEAN NOT NULL DEFAULT FALSE,
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,

    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- allowed-value guard for action
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'crm_procurement_title_rules_action_chk') THEN
        ALTER TABLE crm_procurement_title_rules
            ADD CONSTRAINT crm_procurement_title_rules_action_chk
            CHECK (action IN ('ASSIGN_SUBCATEGORY', 'KEEP',
                              'MOVE_CATEGORY', 'REMOVE_CATEGORY'));
    END IF;
END $$;

-- one rule per (normalization version, normalized title, current category)
CREATE UNIQUE INDEX IF NOT EXISTS crm_procurement_title_rules_unique_idx
    ON crm_procurement_title_rules
       (normalization_version, normalized_title, current_category_code);

-- runtime lookup path
CREATE INDEX IF NOT EXISTS crm_procurement_title_rules_lookup_idx
    ON crm_procurement_title_rules
       (normalization_version, current_category_code, normalized_title)
    WHERE is_active;

COMMIT;
