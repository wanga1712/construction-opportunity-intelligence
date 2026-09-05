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
    SELECT id, queue_id, procurement_id, file_name, created_at
    FROM document_files
    WHERE queue_id IN (148361, 148364)
""")
rows = doc_cur.fetchall()
print(f"FOUND {len(rows)} document_files rows for queue tasks 148361/148364:")
for r in rows:
    print(r)

doc_conn.close()
