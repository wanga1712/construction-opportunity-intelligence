#!/usr/bin/env python3
import sys
import os
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")
sys.path.insert(0, ".")

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

doc_conn = get_doc_db_connection()
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT tableowner FROM pg_tables WHERE tablename = 'document_match_details'")
    print("Table owner:", cur.fetchone())

    cur.execute("SELECT id, validator_version FROM document_match_details WHERE id IN (38182, 38188, 38189, 38190)")
    print("IDs 38182, 38188, 38189, 38190:", [dict(r) for r in cur.fetchall()])
