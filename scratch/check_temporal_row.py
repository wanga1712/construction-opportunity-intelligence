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

crm_dsn = {
    "host": os.getenv("CRM_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("CRM_DB_PORT", "5432")),
    "dbname": os.getenv("CRM_DB_NAME", "crm"),
    "user": os.getenv("CRM_DB_USER", "crm_app"),
    "password": os.getenv("CRM_DB_PASSWORD", ""),
}

doc_conn = psycopg2.connect(**doc_dsn)
crm_conn = psycopg2.connect(**crm_dsn)

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT id, procurement_id, status, created_at, started_at, completed_at, last_error FROM document_processing_queue WHERE procurement_id = 165094")
    print("QUEUE_ROW:", dict(cur.fetchone() or {}))
    cur.execute("SELECT id, procurement_id, file_name, status, created_at FROM document_files WHERE procurement_id = 165094")
    print("FILES:", [dict(r) for r in cur.fetchall()])

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT id, procurement_id, model_name, created_at FROM crm_procurement_shadow_predictions WHERE procurement_id = 165094")
    print("SHADOW_PRED:", [dict(r) for r in cur.fetchall()])

doc_conn.close()
crm_conn.close()
