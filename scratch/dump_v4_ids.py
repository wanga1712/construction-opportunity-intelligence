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
    cur.execute("SELECT id, procurement_id, category_code, validation_status, validator_version, validated_at FROM document_match_details WHERE validator_version = 'v4'")
    rows = cur.fetchall()

print("All V4 Rows in DB count:", len(rows))
for r in rows:
    print(" ", dict(r))
