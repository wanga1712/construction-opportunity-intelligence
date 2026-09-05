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
        WHERE validated_at >= '2026-09-01 18:39:00+00'
           OR validated_at >= NOW() - INTERVAL '10 minutes'
        ORDER BY validated_at DESC
        LIMIT 25
    """)
    rows = [dict(r) for r in cur.fetchall()]

print(f"Total Rows Validated Recently: {len(rows)}")
for r in rows:
    print(" ", r)
