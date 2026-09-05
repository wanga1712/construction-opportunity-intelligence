#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

with open("src/services/commercial_routing_v3/queue_producer.py", "r", encoding="utf-8") as f:
    code = f.read()

import re
funcs = re.findall(r'def\s+([a-zA-Z0-9_]+)\s*\(', code)
print("Functions in queue_producer.py:", funcs)

PYEOF
