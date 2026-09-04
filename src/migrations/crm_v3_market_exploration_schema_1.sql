-- Migration: crm_v3_market_exploration_schema_1.sql
-- Purpose: Schema for market exploration runs and plan items in TEST DB.
-- Notes: OFFLINE/TEST_DB only. Not applied to production DB.

CREATE TABLE IF NOT EXISTS market_exploration_runs (
    run_id VARCHAR(64) PRIMARY KEY,
    run_key VARCHAR(64) NOT NULL UNIQUE,
    run_date DATE NOT NULL,
    source_snapshot VARCHAR(64) NOT NULL DEFAULT 'live_db',
    policy_version VARCHAR(32) NOT NULL DEFAULT 'v1',
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status VARCHAR(32) NOT NULL DEFAULT 'PLANNED',
    cluster_count INTEGER NOT NULL DEFAULT 0,
    procurement_count INTEGER NOT NULL DEFAULT 0,
    estimated_bytes BIGINT NOT NULL DEFAULT 0,
    estimated_cost DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_market_exploration_runs_date ON market_exploration_runs (run_date DESC);
CREATE INDEX IF NOT EXISTS idx_market_exploration_runs_key ON market_exploration_runs (run_key);

CREATE TABLE IF NOT EXISTS market_exploration_plan_items (
    item_id VARCHAR(64) PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL REFERENCES market_exploration_runs(run_id) ON DELETE CASCADE,
    cluster_type VARCHAR(32) NOT NULL,
    cluster_key VARCHAR(64) NOT NULL,
    procurement_id BIGINT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    okpd_code VARCHAR(64) NOT NULL DEFAULT '',
    lot_price DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    selection_reason TEXT NOT NULL DEFAULT '',
    market_volume_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    uncertainty_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    execution_simplicity_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    repeatability_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    research_cost_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    novelty_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    final_exploration_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    selection_stratum VARCHAR(32) NOT NULL DEFAULT 'GENERAL',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_market_exploration_items_run ON market_exploration_plan_items (run_id);
CREATE INDEX IF NOT EXISTS idx_market_exploration_items_pid ON market_exploration_plan_items (procurement_id);
