import sys, psycopg2
sys.path.insert(0, '/opt/CRM_Streamlit')
from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection
doc_conn = get_doc_db_connection()
with doc_conn.cursor() as cur:
    cur.execute('SELECT * FROM document_match_details LIMIT 1')
    print('document_match_details cols:', [desc[0] for desc in cur.description])
