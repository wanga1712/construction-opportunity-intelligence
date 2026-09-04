-- Migration: crm_v3_research_taxonomy_schema_1.sql
-- Purpose: Schema for superuser-managed research taxonomy rules, proposals, audit log, and metadata.
-- Notes: OFFLINE/TEST_DB only during development. Not applied to production DB without authorization.

CREATE TABLE IF NOT EXISTS research_taxonomy_rules (
    rule_id VARCHAR(64) PRIMARY KEY,
    okpd_pattern VARCHAR(64) NOT NULL,
    rule_mode VARCHAR(32) NOT NULL DEFAULT 'NEUTRAL',
    adjustment_weight DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    reason TEXT NOT NULL DEFAULT '',
    created_by VARCHAR(64) NOT NULL DEFAULT 'superuser',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_research_taxonomy_rules_pattern ON research_taxonomy_rules (okpd_pattern);
CREATE INDEX IF NOT EXISTS idx_research_taxonomy_rules_active ON research_taxonomy_rules (is_active);

CREATE TABLE IF NOT EXISTS research_taxonomy_proposals (
    proposal_id VARCHAR(64) PRIMARY KEY,
    okpd_pattern VARCHAR(64) NOT NULL,
    proposed_mode VARCHAR(32) NOT NULL DEFAULT 'NEUTRAL',
    proposed_adjustment DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    evidence_summary TEXT NOT NULL DEFAULT '',
    positive_count INTEGER NOT NULL DEFAULT 0,
    negative_count INTEGER NOT NULL DEFAULT 0,
    sample_pids JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_by VARCHAR(64),
    reviewed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_research_taxonomy_proposals_status ON research_taxonomy_proposals (status);
CREATE INDEX IF NOT EXISTS idx_research_taxonomy_proposals_pattern ON research_taxonomy_proposals (okpd_pattern);

CREATE TABLE IF NOT EXISTS research_taxonomy_audit_log (
    log_id VARCHAR(64) PRIMARY KEY,
    rule_id VARCHAR(64) NOT NULL DEFAULT '',
    action VARCHAR(64) NOT NULL,
    actor VARCHAR(64) NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_research_taxonomy_audit_log_created_at ON research_taxonomy_audit_log (created_at DESC);

CREATE TABLE IF NOT EXISTS research_taxonomy_meta (
    meta_key VARCHAR(64) PRIMARY KEY,
    meta_value JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
