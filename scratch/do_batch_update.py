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
for did in range(38189, 38215):
    cur.execute("""
        UPDATE document_match_details
        SET validation_status = 'REJECTED',
            validation_method = 'QWEN_CONTEXT_V4',
            validation_reason = '[SPECIFICATION_PRODUCT_REQUIREMENT] Test V4 update',
            validated_at = NOW(),
            validator_name = 'context_validator',
            validator_version = 'v4',
            pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
        WHERE id = %s
    """, (did,))
doc_conn.commit()
cur.close()

cur2 = doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur2.execute("SELECT COUNT(*) as cnt FROM document_match_details WHERE validator_version = 'v4'")
print("Total V4 Rows in DB Now:", cur2.fetchone()["cnt"])
cur2.close()
doc_conn.close()
