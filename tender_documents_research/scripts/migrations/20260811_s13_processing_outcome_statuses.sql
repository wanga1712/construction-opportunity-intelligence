-- Explicit S13_V2 migration: align processing result status constraint with terminal parser outcomes.
-- No runtime auto-DDL: apply manually to S13 document_intelligence only.

BEGIN;

ALTER TABLE document_processing_results
    DROP CONSTRAINT IF EXISTS document_processing_results_status_check;

ALTER TABLE document_processing_results
    ADD CONSTRAINT document_processing_results_status_check
    CHECK ((status)::text = ANY (ARRAY[
        'PENDING'::text,
        'COMPLETED'::text,
        'FAILED'::text,
        'UNSUPPORTED'::text,
        'SKIPPED'::text
    ]));

COMMIT;
