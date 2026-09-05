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

from src.services.db_bootstrap import connect_databases
from src.services.commercial_routing_v3.document_links import resolve_document_links

tender_db, radar_db, crm_db, _ = connect_databases()

proc = crm_db.execute_query("SELECT id, source_table, source_id, contract_number FROM crm_procurements WHERE id = 129606")[0]
print("Proc 129606 row:", proc)

res = resolve_document_links(
    source_table=proc.get("source_table"),
    source_id=proc.get("source_id"),
    contract_number=proc.get("contract_number")
)
print("resolve_document_links res:", res)

PYEOF
