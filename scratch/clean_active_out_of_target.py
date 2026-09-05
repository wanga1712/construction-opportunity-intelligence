#!/usr/bin/env python3
import os
import json
import hashlib
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from src.services.commercial_routing_v3.okpd_priors import (
    load_okpd_priors_from_db,
    classify_target_okpd,
    ADMISSION_TARGET,
    ADMISSION_OUT_OF_TARGET,
    ADMISSION_UNKNOWN_OKPD,
)

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
    SELECT id, procurement_id, status, started_at, completed_at, pipeline_generation
    FROM document_processing_queue
    WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
      AND status IN ('PRE_RESEARCH_WAITING', 'PENDING', 'PROCESSING')
""")
active_rows = doc_cur.fetchall()
active_pids = [r["procurement_id"] for r in active_rows]

to_remove_ids = []
if active_pids:
    placeholders = ",".join(["%s"] * len(active_pids))
    crm_cur.execute(f"SELECT id, okpd_code, okpd_name FROM crm_procurements WHERE id IN ({placeholders})", tuple(active_pids))
    active_okpd_map = {r["id"]: r["okpd_code"] for r in crm_cur.fetchall()}
    for r in active_rows:
        code = active_okpd_map.get(r["procurement_id"])
        cls, _ = classify_target_okpd(code, priors)
        if cls in (ADMISSION_OUT_OF_TARGET, ADMISSION_UNKNOWN_OKPD):
            if r["started_at"] is None and r["completed_at"] is None:
                to_remove_ids.append(r["id"])
                print(f"Found unstarted non-target active queue row: id={r['id']}, pid={r['procurement_id']}, status={r['status']}, cls={cls}, okpd={code}")

print(f"TOTAL_UNSTARTED_NON_TARGET_ACTIVE_TO_REMOVE={len(to_remove_ids)}")

if to_remove_ids:
    # Backup
    placeholders = ",".join(["%s"] * len(to_remove_ids))
    doc_cur.execute(f"SELECT * FROM document_processing_queue WHERE id IN ({placeholders})", tuple(to_remove_ids))
    backup_rows = doc_cur.fetchall()
    backup_path = "/opt/CRM_Streamlit/data/backup_active_out_of_target_20260831.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump([dict(r) for r in backup_rows], f, ensure_ascii=False, default=str)
    
    # Delete
    doc_cur.execute(f"DELETE FROM document_processing_queue WHERE id IN ({placeholders})", tuple(to_remove_ids))
    doc_conn.commit()
    print(f"Successfully deleted {len(to_remove_ids)} unstarted non-target active rows.")

crm_conn.close()
doc_conn.close()
