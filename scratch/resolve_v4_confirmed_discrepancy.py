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
            d.id AS detail_id,
            d.procurement_id,
            d.match_id,
            d.category_code,
            d.subcategory_code,
            d.validation_status,
            d.validator_name,
            d.validator_version,
            d.validation_method,
            d.validated_at,
            m.document_name
        FROM document_match_details d
        JOIN document_matches m ON m.id = d.match_id
        WHERE d.pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
          AND d.validation_status = 'CONFIRMED'
          AND d.validator_name = 'context_validator'
          AND LOWER(d.validator_version) = 'v4'
          AND UPPER(d.validation_method) = 'QWEN_CONTEXT_V4'
        ORDER BY d.id
    """)
    v4_confirmed = [dict(r) for r in cur.fetchall()]

    # Also let's check ALL CONFIRMED rows in document_match_details across all generations/versions
    cur.execute("""
        SELECT
            d.id AS detail_id,
            d.procurement_id,
            d.category_code,
            d.validation_status,
            d.validator_version,
            d.validation_method,
            d.pipeline_generation,
            d.validated_at
        FROM document_match_details d
        WHERE d.validation_status = 'CONFIRMED'
        ORDER BY d.id
    """)
    all_confirmed = [dict(r) for r in cur.fetchall()]

print("=" * 80)
print("AUDIT V4 CONFIRMED INPUT DISCREPANCY")
print("=" * 80)
print("V4_CONFIRMED_DETAILS_TOTAL (matching exact filter):", len(v4_confirmed))
print("Sample V4 Confirmed Rows:", v4_confirmed[:10])
print("\nALL CONFIRMED Details Total (any version/generation):", len(all_confirmed))
print("Breakdown of ALL CONFIRMED details:")
for r in all_confirmed:
    print(" ", r)

doc_conn.close()
