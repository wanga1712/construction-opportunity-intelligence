#!/usr/bin/env python3
import sys
import os
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

doc_conn = get_doc_db_connection()
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT 
            COUNT(*) as total_v4_confirmed,
            COUNT(DISTINCT d.procurement_id) as unique_procurements,
            COUNT(DISTINCT m.queue_id) as unique_documents
        FROM document_match_details d
        LEFT JOIN document_matches m ON d.match_id = m.id
        WHERE d.validator_version = 'v4'
          AND d.validation_status = 'CONFIRMED'
          AND d.validator_name = 'context_validator'
          AND d.validation_method = 'QWEN_CONTEXT_V4'
    """)
    totals = dict(cur.fetchone())

    cur.execute("""
        SELECT d.category_code, COUNT(*) as cnt
        FROM document_match_details d
        WHERE d.validator_version = 'v4'
          AND d.validation_status = 'CONFIRMED'
          AND d.validator_name = 'context_validator'
          AND d.validation_method = 'QWEN_CONTEXT_V4'
        GROUP BY d.category_code
        ORDER BY cnt DESC
    """)
    by_cat = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT d.category_code, d.subcategory_code, COUNT(*) as cnt
        FROM document_match_details d
        WHERE d.validator_version = 'v4'
          AND d.validation_status = 'CONFIRMED'
          AND d.validator_name = 'context_validator'
          AND d.validation_method = 'QWEN_CONTEXT_V4'
        GROUP BY d.category_code, d.subcategory_code
        ORDER BY cnt DESC
    """)
    by_subcat = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT COUNT(*) as cnt FROM structured_extraction_runs")
    real_extractions = cur.fetchone()["cnt"]

doc_conn.close()

print("=" * 80)
print("R4 INPUT POPULATION AUDIT")
print("=" * 80)
print("V4_CONFIRMED_DETAILS_TOTAL:", totals["total_v4_confirmed"])
print("UNIQUE_PROCUREMENTS:", totals["unique_procurements"])
print("UNIQUE_DOCUMENTS:", totals["unique_documents"])
print("BY_CATEGORY:", by_cat)
print("BY_SUBCATEGORY:", by_subcat)
print("R4_REAL_EXTRACTIONS_CREATED:", real_extractions)
