#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import subprocess

def run_cmd(cmd):
    return subprocess.check_output(cmd, shell=True, text=True).strip()

print("=== GIT DIFF FOR NON-PYC FILES ===")
print(run_cmd("git diff src/services/annotation_category_gate.py src/services/annotation_state_service.py src/ui/components/analytics_v2/tabs.py"))

PYEOF
