#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')

from src.services.commercial_routing_v3.factual_feeder import _get_doc_db_conn
from src.services.db_bootstrap import connect_databases

tender_db, radar_db, crm_db, _ = connect_databases()
doc_conn = _get_doc_db_conn()
dcur = doc_conn.cursor()

dcur.execute("""
    SELECT DISTINCT procurement_id
    FROM document_files
""")
pids_with_files = [r[0] for r in dcur.fetchall()]

print(f"Total procurements with files in document_intelligence: {len(pids_with_files)}")

p44 = crm_db.execute_query("""
    SELECT p.id, p.source_table, p.contract_number
    FROM crm_procurements p
    WHERE p.id = ANY(%s) AND p.source_table LIKE '%%44%%'
    ORDER BY p.id DESC
    LIMIT 10
""", (pids_with_files,))

p223 = crm_db.execute_query("""
    SELECT p.id, p.source_table, p.contract_number
    FROM crm_procurements p
    WHERE p.id = ANY(%s) AND p.source_table LIKE '%%223%%'
    ORDER BY p.id DESC
    LIMIT 10
""", (pids_with_files,))

canary_44_ids = [r["id"] for r in (p44 or [])]
canary_223_ids = [r["id"] for r in (p223 or [])]

print("CANARY 44-FZ WITH DOCS:", canary_44_ids)
print("CANARY 223-FZ WITH DOCS:", canary_223_ids)

PYEOF
