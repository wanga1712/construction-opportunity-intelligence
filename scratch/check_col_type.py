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
    cur.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'document_match_details' AND column_name = 'validated_at'
    """)
    print("Col type:", cur.fetchone())

    cur.execute("""
        SELECT id, validated_at, validator_version
        FROM document_match_details
        ORDER BY id DESC
        LIMIT 25
    """)
    rows = [dict(r) for r in cur.fetchall()]

print("Highest 25 detail_ids:")
for r in rows:
    print(" ", r)
