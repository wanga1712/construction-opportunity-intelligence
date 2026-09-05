import psycopg2, psycopg2.extras, json

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")
doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")

# Quarantined counts
with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT COUNT(1) as cnt FROM crm_v3_pre_research_snapshots WHERE producer_version LIKE 'v2_invalid_quarantine%%' OR producer_version LIKE 'v1%%'")
    q_snap = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(1) as cnt FROM crm_v3_shadow_predictions WHERE producer_version LIKE 'v2_invalid_quarantine%%' OR producer_version LIKE 'v1%%'")
    q_pred = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(1) as cnt FROM crm_v3_exhaustive_truth WHERE producer_version LIKE 'v2_invalid_quarantine%%' OR producer_version LIKE 'v1%%'")
    q_truth = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(1) as cnt FROM crm_v3_shadow_evaluations WHERE producer_version LIKE 'v2_invalid_quarantine%%' OR producer_version LIKE 'v1%%'")
    q_eval = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(1) as cnt FROM crm_v3_learning_examples WHERE producer_version LIKE 'v2_invalid_quarantine%%' OR producer_version LIKE 'v1%%'")
    q_ex = cur.fetchone()["cnt"]

# Valid v3_real_truth counts
with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT COUNT(1) as cnt FROM crm_v3_pre_research_snapshots WHERE producer_version = 'v3_real_truth'")
    v_snap = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(1) as cnt FROM crm_v3_shadow_predictions WHERE producer_version = 'v3_real_truth'")
    v_pred = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(1) as cnt FROM crm_v3_exhaustive_truth WHERE producer_version = 'v3_real_truth'")
    v_truth = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(1) as cnt FROM crm_v3_shadow_evaluations WHERE producer_version = 'v3_real_truth'")
    v_eval = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(1) as cnt FROM crm_v3_learning_examples WHERE producer_version = 'v3_real_truth'")
    v_ex = cur.fetchone()["cnt"]

# Valid proof items
with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT e.id as eval_id, e.prediction_id, e.truth_id, s.id as snapshot_id,
               s.procurement_id, s.queue_id, s.research_generation_hash, s.snapshot_sha256,
               p.model_run_id, e.false_negative, e.doc_recall_at_1, e.doc_recall_at_3, e.doc_recall_at_5,
               e.mrr, e.first_useful_rank, t.documents_total, t.evidence_count, t.truth_completeness,
               s.document_manifest_json, s.created_at as snap_at, p.created_at as pred_at,
               t.created_at as truth_at, e.created_at as eval_at, p.has_target_decision,
               t.useful_documents_json, t.non_useful_documents_json, t.unknown_documents_json
        FROM crm_v3_shadow_evaluations e
        JOIN crm_v3_shadow_predictions p ON e.prediction_id = p.id
        JOIN crm_v3_pre_research_snapshots s ON p.snapshot_id = s.id
        JOIN crm_v3_exhaustive_truth t ON e.truth_id = t.id
        WHERE e.producer_version = 'v3_real_truth'
        ORDER BY e.id DESC LIMIT 10
    """)
    proof_rows = cur.fetchall()

    proofs = []
    for r in proof_rows:
        cur.execute("SELECT id FROM crm_v3_learning_examples WHERE evaluation_id = %s AND producer_version = 'v3_real_truth'", (r["eval_id"],))
        ex_ids = [ex["id"] for ex in cur.fetchall()]

        manifest = json.loads(r["document_manifest_json"]) if isinstance(r["document_manifest_json"], str) else r["document_manifest_json"]
        useful_docs = json.loads(r["useful_documents_json"]) if isinstance(r["useful_documents_json"], str) else r["useful_documents_json"]
        non_useful_docs = json.loads(r["non_useful_documents_json"]) if isinstance(r["non_useful_documents_json"], str) else r["non_useful_documents_json"]
        unknown_docs = json.loads(r["unknown_documents_json"]) if isinstance(r["unknown_documents_json"], str) else r["unknown_documents_json"]

        proofs.append({
            "PROCUREMENT_ID": r["procurement_id"],
            "QUEUE_ID": r["queue_id"],
            "QUEUE_PROCUREMENT_ID": r["procurement_id"],
            "RESEARCH_GENERATION_HASH": r["research_generation_hash"],
            "SNAPSHOT_ID": r["snapshot_id"],
            "SNAPSHOT_SHA256": r["snapshot_sha256"],
            "MANIFEST_DOCUMENT_COUNT": len(manifest),
            "BLIND_RUN_ID": r["model_run_id"],
            "PREDICTION_ID": r["prediction_id"],
            "PREDICTED_DOCUMENT_COUNT": len(manifest),
            "TRUTH_ID": r["truth_id"],
            "TRUTH_COMPLETENESS": r["truth_completeness"],
            "DOCUMENTS_TOTAL": r["documents_total"],
            "DOCUMENTS_USEFUL": len(useful_docs),
            "DOCUMENTS_NO_TARGET": len(non_useful_docs),
            "DOCUMENTS_UNKNOWN": len(unknown_docs),
            "EVALUATION_ID": r["eval_id"],
            "FALSE_NEGATIVE": r["false_negative"],
            "DOC_RECALL_AT_1": r["doc_recall_at_1"],
            "DOC_RECALL_AT_3": r["doc_recall_at_3"],
            "DOC_RECALL_AT_5": r["doc_recall_at_5"],
            "MRR": r["mrr"],
            "FIRST_USEFUL_RANK": r["first_useful_rank"],
            "LEARNING_EXAMPLE_IDS": ex_ids,
            "TIMESTAMPS": {
                "SNAPSHOT_CREATED_AT": str(r["snap_at"]),
                "PREDICTION_CREATED_AT": str(r["pred_at"]),
                "TRUTH_CREATED_AT": str(r["truth_at"]),
                "EVALUATION_CREATED_AT": str(r["eval_at"])
            }
        })

# Queue counts
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT status, COUNT(1) as cnt FROM document_processing_queue WHERE pipeline_generation = 'S13_V2' GROUP BY status")
    q_counts = {r["status"]: r["cnt"] for r in cur.fetchall()}

print(json.dumps({
    "quarantined": {
        "snapshots": q_snap,
        "predictions": q_pred,
        "truths": q_truth,
        "evaluations": q_eval,
        "examples": q_ex
    },
    "valid": {
        "snapshots": v_snap,
        "predictions": v_pred,
        "truths": v_truth,
        "evaluations": v_eval,
        "examples": v_ex
    },
    "q_counts": q_counts,
    "proofs": proofs
}, indent=2))
