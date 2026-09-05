#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

with open("src/services/commercial_routing_v3/autonomous_worker.py", "r", encoding="utf-8") as f:
    code = f.read()

for l in code.splitlines()[:60]:
    print(l)

PYEOF
