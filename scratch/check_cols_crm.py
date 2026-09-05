import sys, psycopg2, psycopg2.extras
sys.path.insert(0, '/opt/CRM_Streamlit')
from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
)
crm_conn = get_crm_db_connection()
with crm_conn.cursor() as cur:
    cur.execute('SELECT * FROM crm_procurements LIMIT 1')
    cols = [desc[0] for desc in cur.description]
    print('Columns in crm_procurements:', cols)
