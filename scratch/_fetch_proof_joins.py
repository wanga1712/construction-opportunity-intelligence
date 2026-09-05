import psycopg2, psycopg2.extras, json

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT p.id as prediction_id, p.snapshot_id, p.procurement_id, p.research_generation_hash,
               s.snapshot_sha256, p.model_run_id, t.id as truth_id, e.id as eval_id, l.id as example_id
        FROM crm_v3_shadow_predictions p
        JOIN crm_v3_pre_research_snapshots s ON p.snapshot_id = s.id
        LEFT JOIN crm_v3_exhaustive_truth t ON p.procurement_id = t.procurement_id
        LEFT JOIN crm_v3_shadow_evaluations e ON p.id = e.prediction_id
        LEFT JOIN crm_v3_learning_examples l ON e.id = l.evaluation_id
        ORDER BY p.id DESC LIMIT 3
    """)
    rows = cur.fetchall()

print(json.dumps(rows, indent=2))
