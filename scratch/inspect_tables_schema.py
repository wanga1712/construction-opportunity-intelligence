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

for table in ["document_matches", "document_match_details", "document_evidence"]:
    print(f"=== TABLE: {table} ===")
    doc_cur.execute("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = %s
        ORDER BY ordinal_position
    """, (table,))
    for r in doc_cur.fetchall():
        print(f"  {r['column_name']}: {r['data_type']} (nullable={r['is_nullable']}, default={r['column_default']})")
    print()

doc_conn.close()
