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
    cur.execute("SELECT MIN(id), MAX(id), COUNT(*) FROM document_match_details")
    print("Min, Max, Count:", cur.fetchone())

    cur.execute("SELECT DISTINCT validator_version, COUNT(*) FROM document_match_details GROUP BY 1")
    print("Validator versions count:", [dict(r) for r in cur.fetchall()])
