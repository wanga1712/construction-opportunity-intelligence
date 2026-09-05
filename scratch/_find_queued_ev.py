import psycopg2, psycopg2.extras, json

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")
doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT DISTINCT procurement_id FROM crm_v3_raw_source_evidence")
    ev_pids = [r["procurement_id"] for r in cur.fetchall()]

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT id, procurement_id, status, pipeline_generation, research_generation_hash FROM document_processing_queue WHERE procurement_id IN %s", (tuple(ev_pids),))
    q_items = cur.fetchall()

print("ALL QUEUED ITEMS WITH EVIDENCE:")
print(json.dumps(q_items, indent=2))
