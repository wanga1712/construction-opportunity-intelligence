import psycopg2, psycopg2.extras, json

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT pg_get_constraintdef(c.oid) as def
        FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        WHERE t.relname = 'crm_v3_model_inference_runs'
    """)
    cons = [r["def"] for r in cur.fetchall()]

print(json.dumps(cons, indent=2))
