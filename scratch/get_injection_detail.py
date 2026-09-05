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
doc_conn = psycopg2.connect(**doc_dsn)

crm_cur = crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
doc_cur = doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

print("=== 1. CRM TAXONOMY ROW FOR 'инъекц' ===")
crm_cur.execute("""
    SELECT *
    FROM crm_product_subcategory_terms
    WHERE phrase ILIKE '%инъекц%'
""")
terms = crm_cur.fetchall()
for r in terms:
    print("TERM:", dict(r))
    crm_cur.execute("SELECT * FROM crm_product_subcategories WHERE id = %s", (r["subcategory_id"],))
    sub = crm_cur.fetchone()
    print("  SUBCATEGORY:", dict(sub or {}))

print("\n=== 2. ALL MATCH DETAILS FOR 163649 ===")
doc_cur.execute("""
    SELECT d.*, m.document_name
    FROM document_match_details d
    JOIN document_matches m ON m.id = d.match_id
    WHERE d.procurement_id = 163649
    ORDER BY d.id ASC
""")
for r in doc_cur.fetchall():
    print(json.dumps(dict(r), ensure_ascii=False, indent=2, default=str))

print("\n=== 3. ALL EVIDENCE ROWS FOR 163649 ===")
doc_cur.execute("""
    SELECT *
    FROM document_evidence
    WHERE procurement_id = 163649
""")
for r in doc_cur.fetchall():
    print(json.dumps(dict(r), ensure_ascii=False, indent=2, default=str))

crm_conn.close()
doc_conn.close()
