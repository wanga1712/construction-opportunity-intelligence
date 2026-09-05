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

doc_cur.execute("""
    SELECT matched_term, category_code, subcategory_code, COUNT(*) as cnt,
           (ARRAY_AGG(row_data))[1] as sample1,
           (ARRAY_AGG(row_data))[2] as sample2
    FROM document_match_details
    WHERE procurement_id = 997
    GROUP BY matched_term, category_code, subcategory_code
    ORDER BY cnt DESC
    LIMIT 30
""")
matches = doc_cur.fetchall()
print(f"TOTAL UNIQUE MATCHED TERMS FOR 997: {len(matches)}")
for m in matches:
    s1 = m.get("sample1") or {}
    s2 = m.get("sample2") or {}
    txt1 = s1.get("raw_text") or (s1.get("values", {}).get("name") if isinstance(s1.get("values"), dict) else str(s1))
    txt2 = s2.get("raw_text") or (s2.get("values", {}).get("name") if isinstance(s2.get("values"), dict) else str(s2))
    print(f"TERM: {m['matched_term']}, CAT: {m['category_code']}, SUBCAT: {m['subcategory_code']}, COUNT: {m['cnt']}")
    print(f"  Sample 1: {str(txt1)[:100]}")
    print(f"  Sample 2: {str(txt2)[:100]}")

doc_conn.close()
