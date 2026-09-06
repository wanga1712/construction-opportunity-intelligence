-- Migration 004: Create structured_fact_trust_decisions table for durable promotion audit authority

CREATE TABLE IF NOT EXISTS structured_fact_trust_decisions (
    id SERIAL PRIMARY KEY,
    entity_id BIGINT NULL,
    run_id BIGINT NOT NULL,
    from_state VARCHAR(60) NOT NULL,
    to_state VARCHAR(60) NOT NULL,
    decision_reason TEXT NOT NULL,
    review_method VARCHAR(60) NOT NULL,
    reviewed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    reviewed_by VARCHAR(60) NOT NULL,
    canary_batch_id UUID NULL
);

CREATE INDEX IF NOT EXISTS idx_structured_fact_trust_decisions_run 
ON structured_fact_trust_decisions (run_id);

CREATE INDEX IF NOT EXISTS idx_structured_fact_trust_decisions_entity 
ON structured_fact_trust_decisions (entity_id);
