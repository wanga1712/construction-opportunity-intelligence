#!/usr/bin/env python3
import os
import time
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

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

pid = 165094
qid = 148672

crm_conn = psycopg2.connect(**crm_dsn)
doc_conn = psycopg2.connect(**doc_dsn)

crm_cur = crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
doc_cur = doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

for attempt in range(12):
    doc_cur.execute("""
        SELECT id, procurement_id, status, created_at, started_at, completed_at
        FROM document_processing_queue
        WHERE id = %s
    """, (qid,))
    q_row = doc_cur.fetchone()

    # Check blind prediction table (shadow_predictions or similar)
    crm_cur.execute("""
        SELECT id, procurement_id, created_at
        FROM crm_procurement_shadow_predictions
        WHERE procurement_id = %s
        ORDER BY id DESC LIMIT 1
    """, (pid,))
    pred_row = crm_cur.fetchone()

    # Check document files
    doc_cur.execute("""
        SELECT id, procurement_id, created_at
        FROM document_files
        WHERE procurement_id = %s
        ORDER BY id ASC LIMIT 1
    """, (pid,))
    file_row = doc_cur.fetchone()

    print(f"[Attempt {attempt+1}] Queue status={q_row['status']}, Pred={pred_row['created_at'] if pred_row else 'None'}, File={file_row['created_at'] if file_row else 'None'}")
    if pred_row and q_row['status'] != 'PRE_RESEARCH_WAITING':
        break
    time.sleep(3)

print("\n--- TIMELINE FOR PROCUREMENT 165094 ---")
print(f"QUEUE_CREATED_AT={q_row['created_at']}")
print(f"INITIAL_STATUS=PRE_RESEARCH_WAITING")
print(f"BLIND_PREDICTION_AT={pred_row['created_at'] if pred_row else 'PENDING_OR_IN_PROGRESS'}")
print(f"CURRENT_STATUS={q_row['status']}")
print(f"STARTED_AT={q_row['started_at']}")
print(f"FIRST_DOWNLOAD_AT={file_row['created_at'] if file_row else 'NOT_STARTED_YET'}")

crm_conn.close()
doc_conn.close()
