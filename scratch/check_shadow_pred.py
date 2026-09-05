#!/usr/bin/env python3
import os
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

crm_conn = psycopg2.connect(**crm_dsn)
doc_conn = psycopg2.connect(**doc_dsn)

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'crm_procurement_shadow_predictions'")
    print("SHADOW COLS:", [r['column_name'] for r in cur.fetchall()])
    cur.execute("SELECT * FROM crm_procurement_shadow_predictions WHERE procurement_id = 165094")
    print("SHADOW ROW:", cur.fetchall())

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'document_files'")
    print("DOC FILES COLS:", [r['column_name'] for r in cur.fetchall()])
    cur.execute("SELECT * FROM document_files WHERE procurement_id = 165094")
    print("DOC FILES ROWS:", cur.fetchall())

crm_conn.close()
doc_conn.close()
