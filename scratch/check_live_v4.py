import sys
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

conn = get_doc_db_connection()
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT id, procurement_id, validator_version FROM document_match_details WHERE validator_version = 'v4'")
rows = [dict(r) for r in cur.fetchall()]
print("Count of V4 rows in DB:", len(rows))
print("IDs:", [r["id"] for r in rows])
cur.close()
conn.close()
