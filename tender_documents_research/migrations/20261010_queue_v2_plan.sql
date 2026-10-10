-- QUEUE V2 payload columns (additive).
-- The queue receives a ready document plan; it never selects documents itself.
-- Owner: doc_worker (runtime role keeps DML, DDL via approved postgres route).

ALTER TABLE document_processing_queue
    ADD COLUMN IF NOT EXISTS plan_version               text,
    ADD COLUMN IF NOT EXISTS priority_policy_version    text,
    ADD COLUMN IF NOT EXISTS research_action_v2         text,
    ADD COLUMN IF NOT EXISTS source_lifecycle           text,
    ADD COLUMN IF NOT EXISTS project_active             boolean,
    ADD COLUMN IF NOT EXISTS project_end_at             date,
    ADD COLUMN IF NOT EXISTS project_remaining_days     numeric,
    ADD COLUMN IF NOT EXISTS execution_phase            text,
    ADD COLUMN IF NOT EXISTS document_plan_version      text,
    ADD COLUMN IF NOT EXISTS candidate_initial_medal    text,
    ADD COLUMN IF NOT EXISTS current_effective_medal    text,
    ADD COLUMN IF NOT EXISTS required_facts             jsonb,
    ADD COLUMN IF NOT EXISTS required_document_types    jsonb,
    ADD COLUMN IF NOT EXISTS selected_source_document_ids bigint[],
    ADD COLUMN IF NOT EXISTS selected_physical_keys     text[],
    ADD COLUMN IF NOT EXISTS fallback_source_document_ids bigint[],
    ADD COLUMN IF NOT EXISTS selected_documents         jsonb,
    ADD COLUMN IF NOT EXISTS plan_built_at              timestamptz;

COMMENT ON COLUMN document_processing_queue.plan_version IS
    'queue_v2 = plan provided by DOCUMENT_NEEDS_PLAN_V2; NULL = legacy self-selecting downloader';
COMMENT ON COLUMN document_processing_queue.selected_documents IS
    'provenance list: {source_document_id,file_name,document_class,selection_type,selection_reason,required_by_category}';

CREATE INDEX IF NOT EXISTS idx_dpq_queue_v2_claim
    ON document_processing_queue (work_tier, source_start_date DESC, id DESC)
    WHERE plan_version = 'queue_v2';
