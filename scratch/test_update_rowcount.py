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
    cur.execute("""
        UPDATE document_match_details
        SET validation_status = 'REJECTED',
            validation_method = 'QWEN_CONTEXT_V4',
            validation_reason = 'Test update',
            validated_at = NOW(),
            validator_name = 'context_validator',
            validator_version = 'v4'
        WHERE id = 38188
    """)
    print("Rowcount updated:", cur.rowcount)

doc_conn.commit()

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT id, validation_status, validator_version FROM document_match_details WHERE id = 38188")
    print("Row 38188 in DB after commit:", cur.fetchone())

doc_conn.close()
