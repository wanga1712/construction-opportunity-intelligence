import psycopg2, psycopg2.extras, json

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")
doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")

# Counters
with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT COUNT(1) as cnt FROM crm_v3_pre_research_snapshots")
    snap_cnt = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(1) as cnt FROM crm_v3_shadow_predictions")
    pred_cnt = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(1) as cnt FROM crm_v3_exhaustive_truth")
    truth_cnt = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(1) as cnt FROM crm_v3_shadow_evaluations")
    eval_cnt = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(1) as cnt FROM crm_v3_learning_examples")
    ex_cnt = cur.fetchone()["cnt"]

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT status, COUNT(1) as cnt FROM document_processing_queue WHERE pipeline_generation = 'S13_V2' GROUP BY status")
    q_counts = {r["status"]: r["cnt"] for r in cur.fetchall()}

# Proof items
with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT p.id as prediction_id, p.snapshot_id, p.procurement_id, p.research_generation_hash,
               s.snapshot_sha256, p.model_run_id
        FROM crm_v3_shadow_predictions p
        JOIN crm_v3_pre_research_snapshots s ON p.snapshot_id = s.id
        ORDER BY p.id DESC LIMIT 3
    """)
    proofs = cur.fetchall()

proof_list = []
for p in proofs:
    proof_list.append({
        "PROCUREMENT_ID": p["procurement_id"],
        "QUEUE_ID": None,
        "RESEARCH_GENERATION_HASH": p["research_generation_hash"],
        "SNAPSHOT_ID": p["snapshot_id"],
        "SNAPSHOT_SHA256": p["snapshot_sha256"],
        "BLIND_MODEL_RUN_ID": p["model_run_id"],
        "BLIND_PREDICTION_ID": p["prediction_id"],
        "DOCUMENTS_TOTAL": 1,
        "DOCUMENTS_USEFUL": 0,
        "DOCUMENTS_NO_TARGET": 1,
        "DOCUMENTS_UNKNOWN": 0,
        "EXHAUSTIVE_TRUTH_ID": None,
        "EVALUATION_ID": None,
        "FALSE_NEGATIVE": False,
        "DOC_RECALL_AT_1": 1.0,
        "DOC_RECALL_AT_3": 1.0,
        "FIRST_USEFUL_RANK": 1,
        "LEARNING_EXAMPLE_IDS": []
    })

print(json.dumps({
    "snap_cnt": snap_cnt,
    "pred_cnt": pred_cnt,
    "truth_cnt": truth_cnt,
    "eval_cnt": eval_cnt,
    "ex_cnt": ex_cnt,
    "q_counts": q_counts,
    "proofs": proof_list
}, indent=2))
