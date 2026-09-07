-- Procurement-grain pre-research scope and admission authority.
-- Database: CRM (not document_intelligence). Apply only through the controlled
-- migration procedure; application code must not execute this DDL at runtime.

CREATE TABLE IF NOT EXISTS crm_procurement_scope_authority (
    procurement_id BIGINT PRIMARY KEY REFERENCES crm_procurements(id),
    source_lifecycle TEXT NOT NULL,
    procurement_scope_type TEXT NOT NULL,
    scope_confidence NUMERIC NOT NULL,
    scope_method TEXT NOT NULL,
    scope_version TEXT NOT NULL,
    scope_evidence JSONB NOT NULL,
    admission_state TEXT NOT NULL,
    admission_reason TEXT NOT NULL,
    scope_evaluated_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (procurement_scope_type IN (
        'DIRECT_GOODS',
        'WORKS_WITH_EMBEDDED_PRODUCTS',
        'DESIGN_PROJECT',
        'EQUIPMENT_AND_INSTALLATION',
        'SERVICE_WITH_CONSUMABLES',
        'PURE_SERVICE',
        'MIXED',
        'UNKNOWN'
    )),
    CHECK (admission_state IN ('ELIGIBLE', 'EXCLUDED', 'HOLD')),
    CHECK (scope_confidence >= 0 AND scope_confidence <= 1),
    CHECK ((scope_evidence ->> 'post_research_feature_count') = '0')
);

CREATE INDEX IF NOT EXISTS idx_crm_scope_admission
    ON crm_procurement_scope_authority (admission_state, source_lifecycle);
