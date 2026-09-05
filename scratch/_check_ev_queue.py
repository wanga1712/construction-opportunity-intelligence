import psycopg2, psycopg2.extras, json

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")
doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT procurement_id, research_generation_hash FROM document_processing_queue WHERE status = 'COMPLETED' ORDER BY id DESC LIMIT 50")
    q_rows = cur.fetchall()

q_hashes = {r["procurement_id"]: r["research_generation_hash"] for r in q_rows}
pids = tuple(q_hashes.keys())

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT procurement_id, pipeline_generation, research_generation_hash, source_document_id FROM crm_v3_raw_source_evidence WHERE procurement_id IN %s", (pids,))
    ev_matches = cur.fetchall()

print("QUEUED COMPLETED PIDS MATCHING EVIDENCE:")
print(json.dumps(ev_matches, indent=2))
