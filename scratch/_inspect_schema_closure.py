import psycopg2, psycopg2.extras, json

doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")
crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'document_processing_results'")
    dpr_cols = [r["column_name"] for r in cur.fetchall()]

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'crm_product_categories'")
    cat_cols = [r["column_name"] for r in cur.fetchall()]

print("DPR COLS:", json.dumps(dpr_cols, indent=2))
print("CAT COLS:", json.dumps(cat_cols, indent=2))
