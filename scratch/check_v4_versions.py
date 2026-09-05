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
        SELECT validator_version, validation_method, pipeline_generation, COUNT(*) as cnt
        FROM document_match_details
        WHERE validated_at IS NOT NULL
        GROUP BY 1, 2, 3
        ORDER BY cnt DESC
    """)
    rows = [dict(r) for r in cur.fetchall()]

print("Validated Details Version Distribution:")
for r in rows:
    print(" ", r)
