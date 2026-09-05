#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import subprocess

def run_cmd(cmd):
    return subprocess.check_output(cmd, shell=True, text=True).strip()

print("=== STAGING ACCEPTED FILES AND .GITIGNORE ===")
run_cmd("git add src/services/annotation_category_gate.py")
run_cmd("git add src/services/annotation_state_service.py")
run_cmd("git add src/ui/components/analytics_v2/tabs.py")
run_cmd("git add .gitignore")

print("=== GIT DIFF --CACHED --STAT ===")
print(run_cmd("git diff --cached --stat"))

print("=== COMMIT ====")
commit_out = run_cmd('git commit -m "chore(crm): freeze accepted S13 production baseline"')
print(commit_out)

commit_sha = run_cmd("git rev-parse HEAD")
print(f"\nBASELINE_COMMIT_SHA={commit_sha}")

PYEOF
