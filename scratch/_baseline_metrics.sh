#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

from src.services.db_bootstrap import connect_databases

tender_db, radar_db, crm_db, _ = connect_databases()

traces_cnt = crm_db.execute_query("SELECT COUNT(*) as cnt FROM crm_v3_autonomous_analysis_traces")[0]["cnt"]
findings_cnt = crm_db.execute_query("SELECT COUNT(*) as cnt FROM crm_v3_product_findings")[0]["cnt"]
researched_cnt = crm_db.execute_query("SELECT COUNT(DISTINCT procurement_id) as cnt FROM crm_v3_autonomous_analysis_traces")[0]["cnt"]

print(f"BASELINE_TRACES={traces_cnt}")
print(f"BASELINE_FINDINGS={findings_cnt}")
print(f"BASELINE_RESEARCHED_PROCUREMENTS={researched_cnt}")

PYEOF
