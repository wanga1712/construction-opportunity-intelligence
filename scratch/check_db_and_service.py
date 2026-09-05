#!/usr/bin/env python3
import os
import sys
import psycopg2
import psycopg2.extras
import subprocess
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")
sys.path.insert(0, ".")

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

doc_conn = get_doc_db_connection()
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT id, procurement_id, category_code, validation_status, validator_version, validation_method, validated_at, validation_reason
        FROM document_match_details
        WHERE validated_at IS NOT NULL
        ORDER BY validated_at DESC
        LIMIT 10
    """)
    rows = cur.fetchall()

print("Latest 10 Validated Rows in DB:")
for r in rows:
    print(" ", dict(r))

res_st = subprocess.run(["systemctl", "status", "crm-v3-context-validator.service"], capture_output=True, text=True)
print("\nSystemd Service Status:\n", res_st.stdout)

res_j = subprocess.run(["sudo", "journalctl", "-u", "crm-v3-context-validator.service", "-n", "30"], capture_output=True, text=True)
print("\nRecent Journal Logs:\n", res_j.stdout)
