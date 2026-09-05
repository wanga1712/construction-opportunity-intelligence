import psycopg2

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")

ddl_statements = [
    """
    CREATE TABLE IF NOT EXISTS crm_v3_pre_research_snapshots (
        id SERIAL PRIMARY KEY,
        procurement_id BIGINT NOT NULL,
        queue_id BIGINT,
        pipeline_generation VARCHAR(64) NOT NULL DEFAULT 'S13_V2',
        research_generation_hash VARCHAR(64) NOT NULL,
        source_snapshot_json JSONB NOT NULL,
        document_manifest_json JSONB NOT NULL,
        snapshot_sha256 VARCHAR(64) NOT NULL,
        snapshot_schema_version VARCHAR(32) NOT NULL DEFAULT 'v1',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_snapshot_proc_gen UNIQUE (procurement_id, research_generation_hash)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS crm_v3_shadow_predictions (
        id SERIAL PRIMARY KEY,
        snapshot_id BIGINT NOT NULL REFERENCES crm_v3_pre_research_snapshots(id),
        model_run_id BIGINT REFERENCES crm_v3_model_inference_runs(id),
        procurement_id BIGINT NOT NULL,
        research_generation_hash VARCHAR(64) NOT NULL,
        has_target_probability FLOAT,
        has_target_decision VARCHAR(32),
        priority_candidate VARCHAR(32),
        predicted_categories_json JSONB,
        document_ranking_json JSONB,
        overall_confidence FLOAT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS crm_v3_exhaustive_truth (
        id SERIAL PRIMARY KEY,
        procurement_id BIGINT NOT NULL,
        queue_id BIGINT,
        pipeline_generation VARCHAR(64) NOT NULL DEFAULT 'S13_V2',
        research_generation_hash VARCHAR(64) NOT NULL,
        documents_total INT DEFAULT 0,
        documents_terminal_supported INT DEFAULT 0,
        documents_failed_or_unknown INT DEFAULT 0,
        has_target_evidence VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN',
        useful_documents_json JSONB,
        non_useful_documents_json JSONB,
        unknown_documents_json JSONB,
        evidence_count INT DEFAULT 0,
        auto_category_candidates_json JSONB,
        truth_completeness VARCHAR(32) NOT NULL DEFAULT 'COMPLETE',
        truth_source VARCHAR(32) NOT NULL DEFAULT 'AUTO_FACT',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_truth_proc_gen UNIQUE (procurement_id, research_generation_hash)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS crm_v3_shadow_evaluations (
        id SERIAL PRIMARY KEY,
        prediction_id BIGINT NOT NULL REFERENCES crm_v3_shadow_predictions(id),
        truth_id BIGINT NOT NULL REFERENCES crm_v3_exhaustive_truth(id),
        procurement_id BIGINT NOT NULL,
        research_generation_hash VARCHAR(64) NOT NULL,
        false_negative BOOLEAN DEFAULT FALSE,
        doc_recall_at_1 FLOAT DEFAULT 0.0,
        doc_recall_at_3 FLOAT DEFAULT 0.0,
        doc_recall_at_5 FLOAT DEFAULT 0.0,
        mrr FLOAT DEFAULT 0.0,
        first_useful_rank INT,
        simulated_documents_needed INT DEFAULT 0,
        simulated_documents_skipped INT DEFAULT 0,
        error_json JSONB,
        label_source VARCHAR(32) NOT NULL DEFAULT 'AUTO_FACT',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS crm_v3_learning_examples (
        id SERIAL PRIMARY KEY,
        snapshot_id BIGINT REFERENCES crm_v3_pre_research_snapshots(id),
        prediction_id BIGINT REFERENCES crm_v3_shadow_predictions(id),
        truth_id BIGINT REFERENCES crm_v3_exhaustive_truth(id),
        evaluation_id BIGINT REFERENCES crm_v3_shadow_evaluations(id),
        human_annotation_id BIGINT,
        task_type VARCHAR(64) NOT NULL,
        input_json JSONB NOT NULL,
        target_json JSONB NOT NULL,
        label_source VARCHAR(32) NOT NULL DEFAULT 'AUTO_FACT',
        sample_weight FLOAT DEFAULT 1.0,
        dataset_split VARCHAR(32) NOT NULL DEFAULT 'TRAIN',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """
]

with crm_conn.cursor() as cur:
    for stmt in ddl_statements:
        cur.execute(stmt)
crm_conn.commit()
crm_conn.close()
print("SHADOW LEARNING TABLES CREATED SUCCESSFULLY")
