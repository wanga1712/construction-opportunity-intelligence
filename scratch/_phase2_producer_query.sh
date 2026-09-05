#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

with open("src/services/commercial_routing_v3/queue_producer.py", "r", encoding="utf-8") as f:
    code_qp = f.read()

print("=== QUEUE PRODUCER SEARCH CLAUSE & ADMISSION ===")
for line in code_qp.splitlines():
    if any(k in line for k in ["SELECT", "FROM", "WHERE", "JOIN", "procurement_ai_assessments", "crm_procurement_category_opportunities", "crm_procurements"]):
        print("  ", line[:120])

PYEOF
