#!/usr/bin/env python3
import os
import json
import hashlib
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db, match_okpd_priors

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

print("--- 1. AUDIT FALSE FAILED ROWS ---")
doc_cur.execute("""
    SELECT COUNT(*) as cnt
    FROM document_processing_queue
    WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
      AND status = 'FAILED'
      AND last_error = 'OUT_OF_TARGET_OKPD'
""")
false_failed_before = doc_cur.fetchone()["cnt"]
print(f"FALSE_FAILED_ROWS_BEFORE={false_failed_before}")

doc_cur.execute("""
    SELECT COUNT(*) as cnt
    FROM document_processing_queue
    WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
      AND status = 'FAILED'
      AND (last_error != 'OUT_OF_TARGET_OKPD' OR last_error IS NULL)
""")
genuine_failed_before = doc_cur.fetchone()["cnt"]
print(f"GENUINE_FAILED_BEFORE={genuine_failed_before}")

doc_cur.execute("""
    SELECT COUNT(*) as cnt
    FROM document_processing_queue
    WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
      AND status = 'FAILED'
      AND last_error = 'OUT_OF_TARGET_OKPD'
      AND (started_at IS NOT NULL OR completed_at IS NOT NULL)
""")
started_false_failed = doc_cur.fetchone()["cnt"]
print(f"STARTED_OR_COMPLETED_FALSE_FAILED={started_false_failed}")

# Check files table
doc_cur.execute("""
    SELECT COUNT(*) as cnt
    FROM document_files f
    JOIN document_processing_queue q ON q.procurement_id = f.procurement_id
    WHERE q.pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
      AND q.status = 'FAILED'
      AND q.last_error = 'OUT_OF_TARGET_OKPD'
""")
has_files_false_failed = doc_cur.fetchone()["cnt"]
print(f"HAS_FILES_FALSE_FAILED={has_files_false_failed}")

print("\n--- 2. CREATE TARGETED BACKUP ---")
os.makedirs("/opt/CRM_Streamlit/data", exist_ok=True)
backup_path = "/opt/CRM_Streamlit/data/backup_false_failed_out_of_target_20260831.json"

doc_cur.execute("""
    SELECT id, procurement_id, source_table, source_id, contract_number,
           status, pipeline_generation, last_error, category_context, created_at
    FROM document_processing_queue
    WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
      AND status = 'FAILED'
      AND last_error = 'OUT_OF_TARGET_OKPD'
""")
rows = doc_cur.fetchall()

with open(backup_path, "w", encoding="utf-8") as f:
    json.dump([dict(r) for r in rows], f, ensure_ascii=False, default=str)

with open(backup_path, "rb") as f:
    backup_sha256 = hashlib.sha256(f.read()).hexdigest()

print(f"BACKUP_PATH={backup_path}")
print(f"BACKUP_SHA256={backup_sha256}")
print(f"BACKED_UP_ROWS={len(rows)}")

print("\n--- 3. REMOVE UNSTARTED FALSE FAILED ROWS ---")
doc_cur.execute("""
    DELETE FROM document_processing_queue
    WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
      AND status = 'FAILED'
      AND last_error = 'OUT_OF_TARGET_OKPD'
      AND started_at IS NULL
      AND completed_at IS NULL
""")
deleted_count = doc_cur.rowcount
doc_conn.commit()
print(f"FALSE_FAILED_UNSTARTED_REMOVED={deleted_count}")

# Verify counts after deletion
doc_cur.execute("""
    SELECT COUNT(*) as cnt
    FROM document_processing_queue
    WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
      AND status = 'FAILED'
      AND last_error = 'OUT_OF_TARGET_OKPD'
""")
false_failed_remaining = doc_cur.fetchone()["cnt"]
print(f"FALSE_FAILED_UNSTARTED_REMAINING={false_failed_remaining}")

doc_cur.execute("""
    SELECT COUNT(*) as cnt
    FROM document_processing_queue
    WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
      AND status = 'FAILED'
      AND (last_error != 'OUT_OF_TARGET_OKPD' OR last_error IS NULL)
""")
genuine_failed_after = doc_cur.fetchone()["cnt"]
print(f"GENUINE_FAILED_AFTER={genuine_failed_after}")
print(f"REAL_RESEARCH_FAILED_ROWS_DELETED={genuine_failed_before - genuine_failed_after}")

print("\n--- 4. AUDIT COMPLETED OUT-OF-TARGET RESEARCH ---")
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
    SELECT id, procurement_id, status, pipeline_generation
    FROM document_processing_queue
    WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
      AND status = 'COMPLETED'
""")
completed_rows = doc_cur.fetchall()
print(f"TOTAL_COMPLETED_V4={len(completed_rows)}")

completed_pids = [r["procurement_id"] for r in completed_rows]
completed_out_of_target = 0
if completed_pids:
    placeholders = ",".join(["%s"] * len(completed_pids))
    crm_cur.execute(f"SELECT id, okpd_code FROM crm_procurements WHERE id IN ({placeholders})", tuple(completed_pids))
    okpd_map = {r["id"]: r["okpd_code"] for r in crm_cur.fetchall()}
    for r in completed_rows:
        code = okpd_map.get(r["procurement_id"])
        matched = match_okpd_priors(code, priors)
        if not matched:
            completed_out_of_target += 1

print(f"COMPLETED_OUT_OF_TARGET={completed_out_of_target}")
print("COMPLETED_OUT_OF_TARGET_PRESERVED=YES")

crm_conn.close()
doc_conn.close()
