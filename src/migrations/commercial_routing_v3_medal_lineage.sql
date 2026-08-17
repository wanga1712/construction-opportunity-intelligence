-- CRM-V3-MEDAL-LINEAGE-DAILY-REEVALUATION-AND-INFERENCE-RELIABILITY-1
-- S13 derived CRM/routing only. Do not mutate S7 source authority.
-- Historical candidate_medal is NOT copied into candidate_initial_* (unproven).

ALTER TABLE crm_procurement_category_opportunities
    ADD COLUMN IF NOT EXISTS candidate_initial_score NUMERIC,
    ADD COLUMN IF NOT EXISTS candidate_initial_medal TEXT,
    ADD COLUMN IF NOT EXISTS candidate_initial_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS candidate_initial_scoring_version TEXT,
    ADD COLUMN IF NOT EXISTS initial_medal_provenance TEXT NOT NULL DEFAULT 'NOT_HISTORICALLY_AVAILABLE',
    ADD COLUMN IF NOT EXISTS confirmed_base_score NUMERIC,
    ADD COLUMN IF NOT EXISTS confirmed_base_medal TEXT,
    ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS confirmed_scoring_version TEXT,
    ADD COLUMN IF NOT EXISTS current_effective_score NUMERIC,
    ADD COLUMN IF NOT EXISTS current_effective_medal TEXT,
    ADD COLUMN IF NOT EXISTS current_effective_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS current_effective_reason TEXT,
    ADD COLUMN IF NOT EXISTS semantic_hypothesis JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE crm_procurement_category_opportunities
SET
    current_effective_score = COALESCE(current_effective_score, commercial_priority_score),
    current_effective_medal = COALESCE(current_effective_medal, candidate_medal),
    current_effective_at = COALESCE(current_effective_at, updated_at),
    current_effective_reason = COALESCE(current_effective_reason, 'MIGRATION_SNAPSHOT_NOT_INITIAL')
WHERE current_effective_medal IS NULL;

CREATE TABLE IF NOT EXISTS crm_category_opportunity_medal_history (
    id BIGSERIAL PRIMARY KEY,
    procurement_id BIGINT NOT NULL,
    commercial_category_code TEXT,
    opportunity_track TEXT,
    previous_effective_score NUMERIC,
    previous_effective_medal TEXT,
    new_effective_score NUMERIC NOT NULL,
    new_effective_medal TEXT NOT NULL,
    reason TEXT NOT NULL,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lifecycle TEXT,
    timing_phase TEXT,
    scoring_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_medal_history_proc
    ON crm_category_opportunity_medal_history (procurement_id, evaluated_at DESC);

CREATE TABLE IF NOT EXISTS crm_v3_inference_attempts (
    id BIGSERIAL PRIMARY KEY,
    procurement_id BIGINT NOT NULL,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL,
    last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    next_retry_at TIMESTAMPTZ,
    retry_eligible BOOLEAN NOT NULL DEFAULT TRUE,
    input_hash TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    prompt_sha256 TEXT,
    model TEXT,
    failure_reason TEXT,
    failure_class TEXT,
    attempt_history JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_v3_inference_attempts_identity
    ON crm_v3_inference_attempts (procurement_id, input_hash, prompt_version);
