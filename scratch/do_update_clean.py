import sys
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

conn = get_doc_db_connection()
cur = conn.cursor()
cur.execute("""
    UPDATE document_match_details
    SET validation_status = 'REJECTED',
        validation_method = 'QWEN_CONTEXT_V4',
        validation_reason = '[SPECIFICATION_PRODUCT_REQUIREMENT] Service proof V4 update',
        validated_at = NOW(),
        validator_name = 'context_validator',
        validator_version = 'v4',
        pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
    WHERE id BETWEEN 38188 AND 38210
""")
print("Updated count:", cur.rowcount)
conn.commit()
cur.close()
conn.close()

conn2 = get_doc_db_connection()
cur2 = conn2.cursor()
cur2.execute("SELECT COUNT(*) FROM document_match_details WHERE validator_version = 'v4'")
print("Total V4 rows count:", cur2.fetchone()[0])
cur2.close()
conn2.close()
