#!/usr/bin/env python3
import os
import json
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

# 1. Backup files and queue rows
doc_cur.execute("SELECT * FROM document_files WHERE queue_id IN (148361, 148364)")
file_backup = doc_cur.fetchall()
with open("/opt/CRM_Streamlit/data/backup_files_148361_148364.json", "w", encoding="utf-8") as f:
    json.dump([dict(r) for r in file_backup], f, ensure_ascii=False, default=str)

doc_cur.execute("SELECT * FROM document_processing_queue WHERE id IN (148361, 148364)")
queue_backup = doc_cur.fetchall()
with open("/opt/CRM_Streamlit/data/backup_queue_148361_148364.json", "w", encoding="utf-8") as f:
    json.dump([dict(r) for r in queue_backup], f, ensure_ascii=False, default=str)

# 2. Delete files then queue rows
doc_cur.execute("DELETE FROM document_files WHERE queue_id IN (148361, 148364)")
doc_cur.execute("DELETE FROM document_processing_queue WHERE id IN (148361, 148364)")
doc_conn.commit()

print("Cleaned tasks 148361 and 148364.")
doc_conn.close()
