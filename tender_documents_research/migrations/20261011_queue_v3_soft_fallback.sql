-- DOCUMENT_SELECTION_V3: Queue payload carries the soft-fallback provenance.
-- Additive only. Owner: doc_worker (runtime role keeps DML, DDL via approved
-- postgres route: ssh S13 -> sudo -n -u postgres psql -d document_intelligence).

ALTER TABLE document_processing_queue
    ADD COLUMN IF NOT EXISTS soft_fallback_source_document_ids bigint[];

COMMENT ON COLUMN document_processing_queue.soft_fallback_source_document_ids IS
    'selection_type=SOFT_FALLBACK source_document_ids: explicit, ID-scoped '
    'last-resort documents allowed to bypass filename semantic skip at parse time';

COMMENT ON COLUMN document_processing_queue.selected_documents IS
    'provenance list: {source_document_id,physical_key,file_name,category,'
    'document_class,selection_type,selection_reason,required_by_category,required_facts}';
