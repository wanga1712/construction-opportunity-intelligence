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
    SELECT pipeline_generation, count(*) as cnt
    FROM document_evidence
    GROUP BY pipeline_generation
""")
print("DOCUMENT_EVIDENCE BY GENERATION:")
for r in doc_cur.fetchall():
    print(dict(r))

doc_cur.execute("""
    SELECT count(*) as total_v4_evidence
    FROM document_evidence
    WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
""")
v4_ev = doc_cur.fetchone()["total_v4_evidence"]
print(f"\nV4_EVIDENCE_ROWS_BEFORE = {v4_ev}")

doc_cur.execute("""
    SELECT pipeline_generation, count(*) as cnt
    FROM document_match_details
    GROUP BY pipeline_generation
""")
print("\nDOCUMENT_MATCH_DETAILS BY GENERATION:")
for r in doc_cur.fetchall():
    print(dict(r))

doc_conn.close()
