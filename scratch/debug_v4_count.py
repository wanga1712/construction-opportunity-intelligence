#!/usr/bin/env python3
import sys
import os
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")
sys.path.insert(0, ".")

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

doc_conn = get_doc_db_connection()
with doc_conn.cursor() as cur:
    cur.execute("SELECT COUNT(*) FROM document_match_details WHERE validator_version = 'v4'")
    cnt1 = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM document_match_details WHERE LOWER(validator_version) = 'v4'")
    cnt2 = cur.fetchone()[0]

    cur.execute("SELECT DISTINCT validator_version, COUNT(*) FROM document_match_details GROUP BY 1")
    rows = cur.fetchall()

print("cnt1 (v4):", cnt1)
print("cnt2 (lower v4):", cnt2)
print("Group by version:", rows)
doc_conn.close()
