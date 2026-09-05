import sys
import os
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

doc_conn = get_doc_db_connection()
with doc_conn.cursor() as cur:
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'document_match_details'")
    d_cols = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'document_matches'")
    m_cols = [r[0] for r in cur.fetchall()]

print("document_match_details columns:", d_cols)
print("document_matches columns:", m_cols)
doc_conn.close()
