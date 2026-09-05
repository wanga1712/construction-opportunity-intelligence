#!/usr/bin/env python3
"""Inspect raw row_data structure for sample rows."""
import json
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

conn = get_doc_db_connection()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# Sample 5 rows from the last validated batch
cur.execute("""
    SELECT id, matched_term, row_data, context_before, context_after
    FROM document_match_details
    WHERE id IN (35176, 35180, 35200, 35220, 35240, 35250, 35260, 35275)
    ORDER BY id
""")

for row in cur.fetchall():
    print(f"=== ID={row['id']}, TERM='{row['matched_term']}' ===")
    rd = row['row_data']
    if isinstance(rd, dict):
        print(f"  ROW_DATA keys: {list(rd.keys())}")
        for k, v in rd.items():
            val_str = str(v)[:100] if v is not None else "NULL"
            print(f"    {k}: {val_str}")
    elif isinstance(rd, str):
        print(f"  ROW_DATA (str): {rd[:300]}")
    else:
        print(f"  ROW_DATA type={type(rd).__name__}")

    cb = row['context_before']
    ca = row['context_after']
    if isinstance(cb, list):
        print(f"  CONTEXT_BEFORE ({len(cb)} items):")
        for item in cb[:3]:
            print(f"    - {str(item)[:100]}")
    else:
        print(f"  CONTEXT_BEFORE type={type(cb).__name__}, val={str(cb)[:100]}")

    if isinstance(ca, list):
        print(f"  CONTEXT_AFTER ({len(ca)} items):")
        for item in ca[:3]:
            print(f"    - {str(item)[:100]}")
    else:
        print(f"  CONTEXT_AFTER type={type(ca).__name__}, val={str(ca)[:100]}")

conn.close()
