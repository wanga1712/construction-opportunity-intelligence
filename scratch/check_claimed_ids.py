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
        SELECT id, procurement_id, category_code, validation_status, validator_name, validator_version, validation_method, validated_at, validation_reason
        FROM document_match_details
        WHERE id BETWEEN 33800 AND 33830
        ORDER BY id ASC
    """)
    rows = [dict(r) for r in cur.fetchall()]

print(f"Detail IDs 33800..33830 (Count {len(rows)}):")
for r in rows:
    print(" ", r)
