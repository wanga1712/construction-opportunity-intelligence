#!/usr/bin/env python3
import sys
import os
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")
sys.path.insert(0, ".")

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

doc_conn = get_doc_db_connection()
cur = doc_conn.cursor()
try:
    cur.execute("""
        UPDATE document_match_details
        SET validator_version = 'v4'
        WHERE id = 38188
    """)
    print("Update rowcount:", cur.rowcount)
    doc_conn.commit()
    print("Commit succeeded!")
except Exception as e:
    print("Exception on update/commit:", e)
    doc_conn.rollback()

cur.close()

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur2:
    cur2.execute("SELECT id, validator_version FROM document_match_details WHERE id = 38188")
    print("After commit select:", cur2.fetchone())

doc_conn.close()
