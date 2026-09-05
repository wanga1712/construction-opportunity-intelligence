import sys
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

conn = get_doc_db_connection()
with conn.cursor() as cur:
    cur.execute("SELECT table_schema, table_name FROM information_schema.tables WHERE table_name LIKE '%structured%'")
    print("Tables matching '%structured%':", cur.fetchall())
    cur.execute("SHOW search_path")
    print("Current search_path:", cur.fetchone())
conn.close()
