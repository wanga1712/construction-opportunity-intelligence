#!/usr/bin/env python3
import os
import json
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
crm_conn.autocommit = True
doc_conn = psycopg2.connect(**doc_dsn)
doc_conn.autocommit = True

crm_cur = crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
doc_cur = doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

print("=== 1. SEARCH FOR 'инъекц' IN CRM TAXONOMY / KEYWORDS ===")
crm_cur.execute("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public' AND (table_name LIKE '%key%' OR table_name LIKE '%tax%' OR table_name LIKE '%cat%' OR table_name LIKE '%phrase%' OR table_name LIKE '%term%')
""")
tables = [r["table_name"] for r in crm_cur.fetchall()]
print(f"Tables to check in CRM: {tables}")

for t in tables:
    try:
        crm_cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = %s", (t,))
        cols = [r["column_name"] for r in crm_cur.fetchall()]
        text_cols = [c for c in cols if any(k in c for k in ["name", "keyword", "term", "phrase", "code", "text", "pattern"])]
        if text_cols:
            where_clause = " OR ".join([f"{c}::text ILIKE '%инъекц%'" for c in text_cols])
            crm_cur.execute(f"SELECT * FROM {t} WHERE {where_clause}")
            rows = crm_cur.fetchall()
            if rows:
                print(f"\nFOUND IN CRM {t} ({len(rows)} rows):")
                for r in rows:
                    print(dict(r))
    except Exception as e:
        print(f"Error on {t}: {e}")

print("\n=== 2. SEARCH FOR 163649 IN DOCUMENT INTELLIGENCE MATCHES ===")
doc_cur.execute("""
    SELECT *
    FROM document_matches
    WHERE procurement_id = 163649
""")
m_rows = doc_cur.fetchall()
print(f"DOCUMENT_MATCHES FOR 163649: {len(m_rows)}")
for r in m_rows:
    print(dict(r))

doc_cur.execute("""
    SELECT *
    FROM document_match_details
    WHERE procurement_id = 163649
""")
d_rows = doc_cur.fetchall()
print(f"\nDOCUMENT_MATCH_DETAILS FOR 163649: {len(d_rows)}")
for r in d_rows:
    print(dict(r))

doc_cur.execute("""
    SELECT *
    FROM document_evidence
    WHERE procurement_id = 163649
""")
e_rows = doc_cur.fetchall()
print(f"\nDOCUMENT_EVIDENCE FOR 163649: {len(e_rows)}")
for r in e_rows:
    print(dict(r))

crm_conn.close()
doc_conn.close()
