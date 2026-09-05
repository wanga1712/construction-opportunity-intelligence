#!/usr/bin/env python3
import os
import subprocess

def run_cmd(cmd):
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return res.stdout.strip()
    except Exception as e:
        return str(e)

print("=== 1. LS /opt/tender_documents_research ===")
print(run_cmd("ls -la /opt/tender_documents_research"))

print("\n=== 2. CHECK GIT IN /opt/tender_documents_research ===")
print(run_cmd("git -C /opt/tender_documents_research status 2>&1"))

print("\n=== 3. LS document_processor ===")
print(run_cmd("ls -la /opt/tender_documents_research/document_processor"))

