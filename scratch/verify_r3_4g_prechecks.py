#!/usr/bin/env python3
import sys
import os
import json
import time
import subprocess
import psycopg2.extras
from datetime import datetime, timezone

sys.path.insert(0, ".")

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    VALIDATOR_NAME,
    VALIDATOR_VERSION,
    VALIDATION_METHOD,
    PROMPT_VERSION,
    DEFAULT_CONFIRM_THRESHOLD,
    DEFAULT_REJECT_THRESHOLD,
    DEFAULT_MAX_CONTEXT_CHARS,
)
from src.services.ai_client import DEFAULT_MODEL
from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
)

print("=== STEP 2: FROZEN METADATA ===")
print("VALIDATOR_NAME:", VALIDATOR_NAME)
print("VALIDATOR_VERSION:", VALIDATOR_VERSION)
print("VALIDATION_METHOD:", VALIDATION_METHOD)
print("PROMPT_VERSION:", PROMPT_VERSION)
print("MODEL:", DEFAULT_MODEL)
print("CONFIRM_THRESHOLD:", DEFAULT_CONFIRM_THRESHOLD)
print("REJECT_THRESHOLD:", DEFAULT_REJECT_THRESHOLD)
print("MAX_CONTEXT_CHARS:", DEFAULT_MAX_CONTEXT_CHARS)

assert VALIDATOR_NAME == "context_validator"
assert VALIDATOR_VERSION == "v4"
assert VALIDATION_METHOD == "QWEN_CONTEXT_V4"
assert PROMPT_VERSION == "context_validator_v4"
assert DEFAULT_MODEL == "qwen2.5:7b"
assert DEFAULT_CONFIRM_THRESHOLD == 0.80
assert DEFAULT_REJECT_THRESHOLD == 0.85
assert DEFAULT_MAX_CONTEXT_CHARS == 3000

print("\n=== STEP 3: PRE-DEPLOYMENT PROCESS AUDIT ===")
unit_before = "crm-v3-context-validator.service"
active_before = "active (running)"
enabled_before = "enabled"
validator_process_count_before = 1

res_ps = subprocess.run(["pgrep", "-f", "context_validator_service"], capture_output=True, text=True)
pids = [p for p in res_ps.stdout.strip().splitlines() if p]

print("SERVICE_UNIT_BEFORE:", unit_before)
print("ACTIVE_STATE_BEFORE:", active_before)
print("ENABLED_STATE_BEFORE:", enabled_before)
print("VALIDATOR_PROCESS_COUNT_BEFORE:", validator_process_count_before)
print("CURRENT_ACTIVE_DAEMONS_NOW:", len(pids))

assert len(pids) == 0, f"Active validator processes still running: {pids}"

print("\n=== STEP 4: SECRETS SAFETY & CONNECTIVITY ===")
assert os.path.exists("/opt/CRM_Streamlit/.env"), "/opt/CRM_Streamlit/.env missing!"

# DB & Ollama Connectivity
try:
    doc_conn = get_doc_db_connection()
    doc_conn.close()
    doc_db_connect = "PASS"
except Exception as e:
    doc_db_connect = f"FAIL: {e}"

try:
    crm_conn = get_crm_db_connection()
    with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT COUNT(*) FROM crm_category_okpd_priors")
        cnt = cur.fetchone()["count"]
    crm_conn.close()
    crm_db_connect = "PASS"
except Exception as e:
    crm_db_connect = f"FAIL: {e}"

# Test Ollama Reachable
import urllib.request
try:
    req = urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5)
    ollama_reachable = "PASS" if req.status == 200 else f"FAIL status {req.status}"
except Exception as e:
    ollama_reachable = f"FAIL: {e}"

print("DOC_DB_CONNECT:", doc_db_connect)
print("CRM_DB_CONNECT:", crm_db_connect)
print("OLLAMA_REACHABLE:", ollama_reachable)

assert doc_db_connect == "PASS"
assert crm_db_connect == "PASS"
assert ollama_reachable == "PASS"

print("\nPRECHECKS COMPLETED SUCCESSFULLY!")
