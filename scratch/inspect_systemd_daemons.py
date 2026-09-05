#!/usr/bin/env python3
import subprocess

def run_cmd(cmd):
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return res.stdout.strip()
    except Exception as e:
        return str(e)

for s in [
    "tender-docs-daemon.service",
    "tender-docs-daemon-open-2.service",
    "crm-v3-autonomous-worker.service",
]:
    print(f"=== SERVICE: {s} ===")
    print(run_cmd(f"systemctl cat {s}"))
    print()

