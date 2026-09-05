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

tender_db, radar_db, crm_db, _ = connect_databases()

runs = crm_db.execute_query("""
    SELECT id, procurement_id, run_kind, model_name, parse_status, validation_status, created_at
    FROM crm_v3_model_inference_runs
    ORDER BY id DESC
    LIMIT 5
""") or []

print("RECENT INFERENCE RUNS:")
for r in runs:
    print(" ", r)

PYEOF
