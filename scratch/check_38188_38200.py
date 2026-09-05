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
    cur.execute("SELECT id, validator_version, validation_status, validated_at FROM document_match_details WHERE id BETWEEN 38188 AND 38200")
    rows = [dict(r) for r in cur.fetchall()]

print("IDs 38188..38200:")
for r in rows:
    print(" ", r)
doc_conn.close()
