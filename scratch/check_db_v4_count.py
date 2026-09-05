import sys
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

conn = get_doc_db_connection()
cur = conn.cursor()
cur.execute("SELECT validator_version, count(*) FROM document_match_details GROUP BY 1")
print("Versions breakdown:", cur.fetchall())
cur.close()

cur2 = conn.cursor()
cur2.execute("SELECT id, validator_name, validator_version, validation_status, validated_at FROM document_match_details WHERE validator_version = 'v4'")
print("V4 rows:", cur2.fetchall())
cur2.close()
conn.close()
