import psycopg2, psycopg2.extras, json

doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT DISTINCT status FROM document_processing_results")
    statuses = [r["status"] for r in cur.fetchall()]

print("DISTINCT DPR STATUSES:", json.dumps(statuses, indent=2))
