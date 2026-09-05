import psycopg2, psycopg2.extras, json

doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")
crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    doc_tables = [r["table_name"] for r in cur.fetchall()]

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    crm_tables = [r["table_name"] for r in cur.fetchall()]

print(json.dumps({
    "doc_tables": doc_tables,
    "crm_tables": crm_tables
}, indent=2))
