-- EMBEDDED_EXTRACTION_NORMALIZATION_V1 Step 1: idempotent entity identity.
-- A physical position is the same fact across re-runs; a repeat reprocess must
-- reuse it, never duplicate it. Additive, non-destructive.

CREATE UNIQUE INDEX IF NOT EXISTS uq_entity_v3_identity
    ON structured_entities
       (procurement_id, source_document_id, entity_fingerprint, extractor_version)
    WHERE extractor_version IS NOT NULL AND source_document_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_r4_runs_doc_version
    ON structured_extraction_runs (procurement_id, document_name, extractor_version);
