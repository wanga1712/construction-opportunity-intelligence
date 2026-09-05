#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os, json
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')

from src.services.db_bootstrap import connect_databases

tender_db, radar_db, crm_db, _ = connect_databases()

canary_44 = [129606, 116536, 116375, 106994, 106637, 105689, 84475, 80973, 76859, 76286]
canary_223 = [152663, 144476, 142543, 142413, 142394, 139805, 139789, 136065, 136057, 127742]
canary_all = canary_44 + canary_223

traces_cnt = crm_db.execute_query("SELECT COUNT(*) as cnt FROM crm_v3_autonomous_analysis_traces")[0]["cnt"]
findings_cnt = crm_db.execute_query("SELECT COUNT(*) as cnt FROM crm_v3_product_findings")[0]["cnt"]
researched_cnt = crm_db.execute_query("SELECT COUNT(DISTINCT procurement_id) as cnt FROM crm_v3_autonomous_analysis_traces")[0]["cnt"]

print(f"POST_TRACES={traces_cnt}")
print(f"POST_FINDINGS={findings_cnt}")
print(f"POST_RESEARCHED_PROCUREMENTS={researched_cnt}")

canary_findings_cnt = crm_db.execute_query(
    "SELECT COUNT(*) as cnt FROM crm_v3_product_findings WHERE procurement_id = ANY(%s)",
    (canary_all,)
)[0]["cnt"]

canary_traces_cnt = crm_db.execute_query(
    "SELECT COUNT(*) as cnt FROM crm_v3_autonomous_analysis_traces WHERE procurement_id = ANY(%s)",
    (canary_all,)
)[0]["cnt"]

print(f"CANARY_SET_TRACES={canary_traces_cnt}")
print(f"CANARY_SET_FINDINGS={canary_findings_cnt}")

PYEOF
