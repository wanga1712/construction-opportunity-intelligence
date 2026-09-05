import sys
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection, get_crm_db_connection

doc_conn = get_doc_db_connection()
with doc_conn.cursor() as cur:
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    doc_tables = [r[0] for r in cur.fetchall()]
doc_conn.close()

crm_conn = get_crm_db_connection()
with crm_conn.cursor() as cur:
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    crm_tables = [r[0] for r in cur.fetchall()]
crm_conn.close()

print("doc_db tables:", doc_tables)
print("crm_db tables:", crm_tables)
