#!/usr/bin/env python3
import os
import subprocess

def run_cmd(cmd):
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return res.stdout.strip()
    except Exception as e:
        return str(e)

print("=== 1. SYSTEMD SERVICES ===")
print(run_cmd("systemctl list-unit-files | grep -E 'doc|crm|tender|shadow'"))

print("\n=== 2. CAT SYSTEMD SERVICE (document processor / workers) ===")
for s in ["document-processor", "document_processor", "crm-v3-shadow-predictor", "tender-document-worker", "tender_documents_research"]:
    out = run_cmd(f"systemctl cat {s} 2>&1")
    if "No files found" not in out:
        print(f"\n--- SERVICE {s} ---")
        print(out)

print("\n=== 3. RUNTIME REPOSITORIES ON S13 ===")
for p in ["/opt/CRM_Streamlit", "/opt/tender_documents_research", "/opt/pythonProject89"]:
    if os.path.exists(p):
        print(f"\nPATH: {p}")
        git_dir = os.path.join(p, ".git")
        if os.path.exists(git_dir):
            branch = run_cmd(f"git -C {p} branch --show-current")
            head = run_cmd(f"git -C {p} rev-parse HEAD")
            remote = run_cmd(f"git -C {p} remote -v")
            status = run_cmd(f"git -C {p} status --short")
            print(f"  GIT_REPO: YES")
            print(f"  BRANCH: {branch}")
            print(f"  HEAD: {head}")
            print(f"  REMOTE:\n{remote}")
            print(f"  DIRTY_COUNT: {len(status.splitlines()) if status else 0}")
            if status:
                print(f"  STATUS:\n{status[:500]}")
        else:
            print("  GIT_REPO: NO")

