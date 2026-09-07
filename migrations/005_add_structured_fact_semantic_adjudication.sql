-- Migration 005: independent semantic adjudication for structured-fact canaries

CREATE TABLE IF NOT EXISTS structured_fact_semantic_adjudications (
    id BIGSERIAL PRIMARY KEY,
    entity_id BIGINT NOT NULL REFERENCES structured_entities(id) ON DELETE CASCADE,
    run_id BIGINT NOT NULL REFERENCES structured_extraction_runs(id) ON DELETE CASCADE,
    canary_batch_id UUID NOT NULL,
    verdict VARCHAR(40) NOT NULL,
    commercial_type_valid BOOLEAN NOT NULL,
    product_evidence_valid BOOLEAN NOT NULL,
    quantity_product_bound BOOLEAN,
    unit_price_evidence_valid BOOLEAN,
    total_price_evidence_valid BOOLEAN,
    adjudicated_by VARCHAR(120) NOT NULL,
    adjudication_method VARCHAR(80) NOT NULL,
    source_quote TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_structured_fact_adjudication_verdict CHECK (
        verdict IN ('PRODUCT_CORRECT', 'PRODUCT_INCORRECT', 'WRONG_ENTITY_TYPE', 'AMBIGUOUS')
    ),
    CONSTRAINT ck_structured_fact_adjudication_method CHECK (
        adjudication_method = 'INDEPENDENT_SEMANTIC_REVIEW'
    )
);

CREATE INDEX IF NOT EXISTS idx_structured_fact_adjudications_entity
ON structured_fact_semantic_adjudications (entity_id);

CREATE INDEX IF NOT EXISTS idx_structured_fact_adjudications_batch
ON structured_fact_semantic_adjudications (canary_batch_id);
