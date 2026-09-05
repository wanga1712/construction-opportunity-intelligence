import psycopg2, psycopg2.extras, json

doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT id, procurement_id, queue_lane, status FROM document_processing_queue WHERE status = 'PENDING'")
    pend = cur.fetchall()

print("PENDING QUEUE ITEMS:")
print(json.dumps(pend, indent=2))
