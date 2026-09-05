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
        SELECT validator_version, validation_status, COUNT(*) as cnt
        FROM document_match_details
        GROUP BY validator_version, validation_status
        ORDER BY validator_version, validation_status
    """)
    rows = [dict(r) for r in cur.fetchall()]

print("Document match details breakdown by version and status:")
for r in rows:
    print(" ", r)

doc_conn.close()
