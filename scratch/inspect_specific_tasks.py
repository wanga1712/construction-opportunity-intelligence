#!/usr/bin/env python3
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

doc_dsn = {
    "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
    "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
    "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
    "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
}

doc_conn = psycopg2.connect(**doc_dsn)
doc_cur = doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

doc_cur.execute("""
    SELECT id, procurement_id, status, started_at, completed_at, worker_id, last_error
    FROM document_processing_queue
    WHERE id IN (148361, 148364)
""")
print("QUEUE ROWS:")
for r in doc_cur.fetchall():
    print(r)

doc_cur.execute("""
    SELECT id, queue_id, procurement_id, file_name, file_url, status, local_path, created_at
    FROM document_files
    WHERE queue_id IN (148361, 148364) OR procurement_id IN (163846, 163849)
""")
print("\nFILE ROWS:")
for r in doc_cur.fetchall():
    print(r)

doc_conn.close()
