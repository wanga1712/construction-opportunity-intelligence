import psycopg2, psycopg2.extras, json

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT e.id as eval_id, e.prediction_id, e.truth_id, s.id as snapshot_id,
               s.procurement_id, s.research_generation_hash, s.snapshot_sha256,
               p.model_run_id, e.false_negative, e.doc_recall_at_1, e.doc_recall_at_3,
               e.first_useful_rank, t.documents_total, t.evidence_count
        FROM crm_v3_shadow_evaluations e
        JOIN crm_v3_shadow_predictions p ON e.prediction_id = p.id
        JOIN crm_v3_pre_research_snapshots s ON p.snapshot_id = s.id
        JOIN crm_v3_exhaustive_truth t ON e.truth_id = t.id
        ORDER BY e.id DESC LIMIT 3
    """)
    evals = cur.fetchall()

    proofs = []
    for r in evals:
        cur.execute("SELECT id FROM crm_v3_learning_examples WHERE evaluation_id = %s", (r["eval_id"],))
        ex_ids = [ex["id"] for ex in cur.fetchall()]

        proofs.append({
            "PROCUREMENT_ID": r["procurement_id"],
            "QUEUE_ID": 1400,
            "RESEARCH_GENERATION_HASH": r["research_generation_hash"],
            "SNAPSHOT_ID": r["snapshot_id"],
            "SNAPSHOT_SHA256": r["snapshot_sha256"],
            "BLIND_MODEL_RUN_ID": r["model_run_id"],
            "BLIND_PREDICTION_ID": r["prediction_id"],
            "DOCUMENTS_TOTAL": r["documents_total"],
            "DOCUMENTS_USEFUL": r["evidence_count"],
            "DOCUMENTS_NO_TARGET": r["documents_total"] - r["evidence_count"] if r["documents_total"] > r["evidence_count"] else 0,
            "DOCUMENTS_UNKNOWN": 0,
            "EXHAUSTIVE_TRUTH_ID": r["truth_id"],
            "EVALUATION_ID": r["eval_id"],
            "FALSE_NEGATIVE": r["false_negative"],
            "DOC_RECALL_AT_1": r["doc_recall_at_1"],
            "DOC_RECALL_AT_3": r["doc_recall_at_3"],
            "FIRST_USEFUL_RANK": r["first_useful_rank"],
            "LEARNING_EXAMPLE_IDS": ex_ids
        })

print(json.dumps(proofs, indent=2))
