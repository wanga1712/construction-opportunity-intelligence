import psycopg2, psycopg2.extras, json, subprocess, hashlib, os

doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")
crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")

# Date reconciliation for 2026-08-29
with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT COUNT(1) as cnt FROM crm_procurements WHERE crm_created_at::date = '2026-08-29'")
    src_total = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(1) as cnt FROM crm_procurements WHERE crm_created_at::date = '2026-08-29' AND (crm_stage = 'torgi' OR award_status = 'submission_open')")
    eligible_total = cur.fetchone()["cnt"]

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT COUNT(1) as cnt FROM document_processing_queue WHERE created_at::date = '2026-08-29'")
    q_total = cur.fetchone()["cnt"]

    cur.execute("SELECT status, COUNT(1) as cnt FROM document_processing_queue WHERE created_at::date = '2026-08-29' GROUP BY status")
    q_status = {r["status"]: r["cnt"] for r in cur.fetchall()}

print(json.dumps({
    "src_total": src_total,
    "eligible_total": eligible_total,
    "q_total": q_total,
    "q_status": q_status
}, indent=2))
