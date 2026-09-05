import psycopg2, psycopg2.extras, json

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT id, procurement_id, useful_documents_json, has_target_evidence
        FROM crm_v3_exhaustive_truth
        WHERE jsonb_array_length(useful_documents_json::jsonb) > 0 OR has_target_evidence = 'YES'
    """)
    pos_truths = cur.fetchall()

print(json.dumps(pos_truths, indent=2))
