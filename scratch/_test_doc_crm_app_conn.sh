#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os, psycopg2, psycopg2.extras
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')

pwd = os.getenv("CRM_DB_PASSWORD") or os.getenv("DB_PASSWORD")
user = os.getenv("CRM_DB_USER") or "crm_app"

print(f"Connecting to document_intelligence as user={user}...")
conn = psycopg2.connect(host="127.0.0.1", port=5432, dbname="document_intelligence", user=user, password=pwd)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

cur.execute("SELECT count(*) as cnt FROM document_processing_queue")
cnt = cur.fetchone()["cnt"]
print(f"DOCUMENT_PROCESSING_QUEUE COUNT = {cnt}")

cur.execute("SELECT count(*) as cnt FROM document_match_details")
cnt_matches = cur.fetchone()["cnt"]
print(f"DOCUMENT_MATCH_DETAILS COUNT = {cnt_matches}")

conn.close()

PYEOF
