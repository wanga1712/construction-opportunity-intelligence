#!/usr/bin/env python3
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db, classify_target_okpd, ADMISSION_OUT_OF_TARGET

load_dotenv("/opt/CRM_Streamlit/.env")

crm_dsn = {
    "host": os.getenv("CRM_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("CRM_DB_PORT", "5432")),
    "dbname": os.getenv("CRM_DB_NAME", "crm"),
    "user": os.getenv("CRM_DB_USER", "crm_app"),
    "password": os.getenv("CRM_DB_PASSWORD", ""),
}

doc_dsn = {
    "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
    "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
    "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
    "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
}

crm_conn = psycopg2.connect(**crm_dsn)
doc_conn = psycopg2.connect(**doc_dsn)

crm_cur = crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
doc_cur = doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

class CrmDbWrapper:
    def __init__(self, conn):
        self.conn = conn
    def execute_query(self, sql, params=None):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()

crm_db = CrmDbWrapper(crm_conn)
priors = load_okpd_priors_from_db(crm_db)

doc_cur.execute("""
    SELECT id, procurement_id, status, started_at, completed_at, last_error, worker_id, pipeline_generation
    FROM document_processing_queue
    WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
      AND status IN ('PRE_RESEARCH_WAITING', 'PENDING', 'PROCESSING')
""")
active_rows = doc_cur.fetchall()
for r in active_rows:
    crm_cur.execute("SELECT id, okpd_code, okpd_name FROM crm_procurements WHERE id = %s", (r["procurement_id"],))
    proc = crm_cur.fetchone()
    code = proc["okpd_code"] if proc else None
    cls, _ = classify_target_okpd(code, priors)
    if cls == ADMISSION_OUT_OF_TARGET:
        print(f"OUT_OF_TARGET_ACTIVE: queue_id={r['id']}, pid={r['procurement_id']}, status={r['status']}, started_at={r['started_at']}, last_error={r['last_error']}, okpd={code}, okpd_name={proc['okpd_name'] if proc else None}")

crm_conn.close()
doc_conn.close()
