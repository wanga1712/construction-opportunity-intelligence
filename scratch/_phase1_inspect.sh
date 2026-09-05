#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import subprocess, json

def run_cmd(cmd):
    return subprocess.check_output(cmd, shell=True, text=True).strip()

print("=== GIT BRANCH -AVV ===")
print(run_cmd("git branch -avv"))

print("\n=== GIT LOG -20 ===")
print(run_cmd("git log --oneline --decorate -20"))

print("\n=== GIT STATUS --SHORT ===")
status_short = run_cmd("git status --short")
print(status_short)

print("\n=== TRACKED PYC FILES ===")
pyc_files = run_cmd("git ls-files | grep -E '(^|/)__pycache__/|\\.pyc$' || true")
print(f"TRACKED_PYC_BEFORE count={len(pyc_files.splitlines()) if pyc_files else 0}")
if pyc_files:
    print("Sample tracked pyc files:")
    for line in pyc_files.splitlines()[:10]:
        print("  ", line)

print("\n=== NON-PYC MODIFIED/UNTRACKED FILES ===")
non_pyc = [l for l in status_short.splitlines() if "__pycache__" not in l and not l.endswith(".pyc")]
for l in non_pyc:
    print("  ", l)

PYEOF
