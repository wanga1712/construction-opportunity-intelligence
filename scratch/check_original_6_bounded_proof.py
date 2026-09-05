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
            d.category_code,
            d.subcategory_code,
            d.validation_status AS current_status,
            d.validated_at AS current_validated_at,
            d.validator_version AS current_validator_version,
            d.validation_method AS current_validation_method,
            d.pipeline_generation
        FROM document_match_details d
        WHERE d.id BETWEEN 38182 AND 38187
        ORDER BY d.id ASC
    """)
    rows = [dict(r) for r in cur.fetchall()]

print("ORIGINAL 6 BOUNDED PROOF DETAILS (38182..38187):")
for r in rows:
    print(" ", r)

doc_conn.close()
