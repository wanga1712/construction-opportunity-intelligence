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
cur.execute("""
    UPDATE document_match_details
    SET validation_status = 'REJECTED',
        validation_method = 'QWEN_CONTEXT_V4',
        validation_reason = '[SPECIFICATION_PRODUCT_REQUIREMENT] Test V4 update',
        validated_at = NOW(),
        validator_name = 'context_validator',
        validator_version = 'v4'
    WHERE id = 38188
""")
print("UPDATE rowcount:", cur.rowcount)
doc_conn.commit()
cur.close()

cur2 = doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur2.execute("SELECT id, validator_version FROM document_match_details WHERE id = 38188")
print("Fetched after commit:", cur2.fetchone())
cur2.close()

doc_conn.close()

doc_conn3 = get_doc_db_connection()
cur3 = doc_conn3.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur3.execute("SELECT id, validator_version FROM document_match_details WHERE id = 38188")
print("Fetched in doc_conn3:", cur3.fetchone())
cur3.close()
doc_conn3.close()
