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
    for did in range(38188, 38210):
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

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT COUNT(*) as cnt FROM document_match_details WHERE validator_version = 'v4' AND pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'")
    v4_cnt = cur.fetchone()["cnt"]

doc_conn.close()
print("Total V4 S13_V4_EXHAUSTIVE_CONTEXT Rows in DB Now:", v4_cnt)
