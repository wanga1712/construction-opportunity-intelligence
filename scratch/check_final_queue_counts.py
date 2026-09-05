#!/usr/bin/env python3
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db, classify_target_okpd, ADMISSION_OUT_OF_TARGET, ADMISSION_UNKNOWN_OKPD

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
    SELECT status, COUNT(*) as cnt
    FROM document_processing_queue
    WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
    GROUP BY status
    ORDER BY status
""")
queue_status_counts = {r["status"]: r["cnt"] for r in doc_cur.fetchall()}
print(f"PRE_RESEARCH_WAITING={queue_status_counts.get('PRE_RESEARCH_WAITING', 0)}")
print(f"PENDING={queue_status_counts.get('PENDING', 0)}")
print(f"PROCESSING={queue_status_counts.get('PROCESSING', 0)}")
print(f"COMPLETED={queue_status_counts.get('COMPLETED', 0)}")
print(f"FAILED={queue_status_counts.get('FAILED', 0)}")
print(f"NO_LINKS={queue_status_counts.get('NO_LINKS', 0)}")

# Check active rows for out of target or unknown okpd
doc_cur.execute("""
    SELECT id, procurement_id, status
    FROM document_processing_queue
    WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
      AND status IN ('PRE_RESEARCH_WAITING', 'PENDING', 'PROCESSING')
""")
active_rows = doc_cur.fetchall()
active_pids = [r["procurement_id"] for r in active_rows]

# Fetch all active okpds in batches of 5000
active_okpd_map = {}
for i in range(0, len(active_pids), 5000):
    chunk = active_pids[i:i+5000]
    placeholders = ",".join(["%s"] * len(chunk))
    crm_cur.execute(f"SELECT id, okpd_code FROM crm_procurements WHERE id IN ({placeholders})", tuple(chunk))
    for r in crm_cur.fetchall():
        active_okpd_map[r["id"]] = r["okpd_code"]

out_of_target_active = 0
unknown_okpd_active = 0

for r in active_rows:
    code = active_okpd_map.get(r["procurement_id"])
    cls, _ = classify_target_okpd(code, priors)
    if cls == ADMISSION_OUT_OF_TARGET:
        out_of_target_active += 1
    elif cls == ADMISSION_UNKNOWN_OKPD:
        unknown_okpd_active += 1

print(f"OUT_OF_TARGET_ACTIVE_QUEUE_ROWS={out_of_target_active}")
print(f"UNKNOWN_OKPD_ACTIVE_QUEUE_ROWS={unknown_okpd_active}")

crm_conn.close()
doc_conn.close()
