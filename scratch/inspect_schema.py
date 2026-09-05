import sys
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

conn = get_doc_db_connection()

with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'document_match_details'")
    print("document_match_details columns:", [r["column_name"] for r in cur.fetchall()])
    
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'document_evidence'")
    print("document_evidence columns:", [r["column_name"] for r in cur.fetchall()])

conn.close()
