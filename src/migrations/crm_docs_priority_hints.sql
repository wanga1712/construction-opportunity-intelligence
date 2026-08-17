-- CRM docs priority hints (CRM-owned derived state).
-- Apply only via controlled migration WIP — never from runtime app paths.

CREATE TABLE IF NOT EXISTS crm_docs_priority_hints (
    id BIGSERIAL PRIMARY KEY,
    tender_id BIGINT NOT NULL,
    registry_type TEXT NOT NULL,
    contract_number TEXT,
    contour TEXT NOT NULL,
    ai_priority_score INTEGER NOT NULL DEFAULT 0,
    ai_profile TEXT,
    ai_reason TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tender_id, registry_type)
);

CREATE INDEX IF NOT EXISTS ix_crm_docs_priority_hints_contour
    ON crm_docs_priority_hints(contour, ai_priority_score DESC, updated_at DESC);

COMMENT ON TABLE crm_docs_priority_hints IS
    'CRM-owned docs priority hints; WRITE crm_db only; no runtime auto-DDL';
