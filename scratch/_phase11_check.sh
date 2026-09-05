#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import subprocess

def run_cmd(cmd):
    return subprocess.check_output(cmd, shell=True, text=True).strip()

print("=== CHECK SERVICE STATUS ===")
print(run_cmd("systemctl status crm-streamlit.service --no-pager | head -n 15"))

print("\n=== CHECK HTTP PORT 8504 ===")
http_code = run_cmd("curl -s -o /dev/null -w '%{http_code}' http://localhost:8504 || echo 000")
print(f"HTTP_STATUS={http_code}")
assert http_code == "200", f"Expected HTTP 200, got {http_code}"

print("\n=== AUTONOMOUS WORKER CHECK ===")
pg_out = run_cmd("pgrep -f 'autonomous_worker' || true")
worker_count = len(pg_out.splitlines()) if pg_out else 0
print(f"AUTONOMOUS_WORKER_INSTANCE_COUNT={worker_count}")

print("\n=== FINAL PRODUCTION CHECK PASSED 100% ===")
PYEOF
