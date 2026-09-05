#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import subprocess

def run_cmd(cmd):
    return subprocess.check_output(cmd, shell=True, text=True).strip()

pyc_files = run_cmd("git ls-files | grep -E '(^|/)__pycache__/|\\.pyc$' || true").splitlines()
print(f"Tracked pyc before: {len(pyc_files)}")

if pyc_files:
    # Remove tracked pyc files from git index
    cmd = "git rm --cached -f " + " ".join(f'"{f}"' for f in pyc_files)
    run_cmd(cmd)
    print("Removed tracked pyc files from index.")

# Ensure .gitignore has __pycache__/ and *.pyc
gitignore_path = "/opt/CRM_Streamlit_rescue/.gitignore"
with open(gitignore_path, "r", encoding="utf-8") as f:
    gi_content = f.read()

gi_additions = []
if "__pycache__/" not in gi_content:
    gi_additions.append("__pycache__/")
if "*.pyc" not in gi_content:
    gi_additions.append("*.pyc")
if "*.py[cod]" not in gi_content:
    gi_additions.append("*.py[cod]")

if gi_additions:
    with open(gitignore_path, "a", encoding="utf-8") as f:
        f.write("\n" + "\n".join(gi_additions) + "\n")
    print("Updated .gitignore with pyc rules.")

pyc_after = run_cmd("git ls-files | grep -E '(^|/)__pycache__/|\\.pyc$' || true")
print(f"TRACKED_PYC_AFTER={len(pyc_after.splitlines()) if pyc_after else 0}")
assert len(pyc_after.splitlines() if pyc_after else []) == 0, "tracked pyc files remain!"

PYEOF
