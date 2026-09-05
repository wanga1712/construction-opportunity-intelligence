#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

print("=== QUEUE PRODUCER INSPECTION ===")
with open("src/services/commercial_routing_v3/queue_producer.py", "r", encoding="utf-8") as f:
    code_qp = f.read()

print(f"queue_producer.py length: {len(code_qp.splitlines())} lines")
for i, l in enumerate(code_qp.splitlines()[:50]):
    print(f"{i+1:3d}: {l}")

print("\n=== RESEARCH QUEUE LIFECYCLE INSPECTION ===")
with open("src/services/commercial_routing_v3/research_queue_lifecycle.py", "r", encoding="utf-8") as f:
    code_rql = f.read()

print(f"research_queue_lifecycle.py length: {len(code_rql.splitlines())} lines")
for i, l in enumerate(code_rql.splitlines()[:60]):
    print(f"{i+1:3d}: {l}")

PYEOF
