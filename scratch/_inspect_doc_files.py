import psycopg2, psycopg2.extras, json

doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'document_files'")
    cols = [r["column_name"] for r in cur.fetchall()]

print(json.dumps(cols, indent=2))
