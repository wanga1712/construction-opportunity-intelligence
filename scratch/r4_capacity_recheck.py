import sys
import os
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection, PIPELINE_GENERATION

conn = get_doc_db_connection()

blacklist = {38319, 38324, 38325, 38373, 38417}

with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT d.id AS detail_id, d.procurement_id, d.category_code, d.subcategory_code
        FROM document_match_details d
        WHERE d.pipeline_generation = %s
          AND d.validator_name = 'context_validator'
          AND LOWER(d.validator_version) = 'v4'
          AND UPPER(d.validation_method) = 'QWEN_CONTEXT_V4'
          AND d.validation_status = 'CONFIRMED'
        ORDER BY d.id ASC
    """, (PIPELINE_GENERATION,))
    confirmed_rows = cur.fetchall()

trusted_total = len(confirmed_rows)
fresh_confirmed = [r for r in confirmed_rows if r["detail_id"] not in blacklist]
fresh_total = len(fresh_confirmed)

print("=" * 80)
print("FRESH R4 CAPACITY AUDIT")
print("=" * 80)
print(f"TRUSTED_V4_CONFIRMED_TOTAL: {trusted_total}")
print(f"FRESH_R4_CONFIRMED_AFTER_BLACKLIST: {fresh_total}")
print(f"EXTRACTOR_CALLS: 0")

conn.close()
