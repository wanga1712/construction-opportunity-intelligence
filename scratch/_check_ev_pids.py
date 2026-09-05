import psycopg2, psycopg2.extras, json

doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT DISTINCT procurement_id, status, research_generation_hash FROM document_processing_queue WHERE pipeline_generation = 'S13_V2' LIMIT 50")
    rows = cur.fetchall()

print("DOCUMENT_INTELLIGENCE QUEUE SAMPLE:")
print(json.dumps(rows, indent=2, default=str))

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")
with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT DISTINCT procurement_id FROM crm_v3_raw_source_evidence WHERE pipeline_generation = 'S13_V2'")
    ev_pids = [r["procurement_id"] for r in cur.fetchall()]

print("CRM EVIDENCE PIDS IN S13_V2:", ev_pids)
