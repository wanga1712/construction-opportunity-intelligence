ALTER TABLE document_processing_queue
ADD COLUMN procurement_scope_type VARCHAR,
ADD COLUMN procurement_scope_confidence NUMERIC,
ADD COLUMN procurement_scope_source VARCHAR,
ADD COLUMN procurement_scope_reason TEXT,
ADD COLUMN procurement_scope_model VARCHAR,
ADD COLUMN procurement_scope_version VARCHAR,
ADD COLUMN procurement_scope_scored_at TIMESTAMPTZ;

ALTER TABLE structured_entities
ADD COLUMN product_relation VARCHAR,
ADD COLUMN product_relation_confidence NUMERIC,
ADD COLUMN product_relation_source VARCHAR,
ADD COLUMN product_relation_reason TEXT,
ADD COLUMN product_relation_scored_at TIMESTAMPTZ;
