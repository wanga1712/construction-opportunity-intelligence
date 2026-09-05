#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os, psycopg2, psycopg2.extras
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

# Connect via local unix socket / peer auth or default params
try:
    conn = psycopg2.connect(dbname="document_intelligence", host="/var/run/postgresql", user="doc_worker")
except Exception as e:
    try:
        conn = psycopg2.connect(dbname="document_intelligence", user="doc_worker")
    except Exception as e2:
        try:
            conn = psycopg2.connect("dbname=document_intelligence")
        except Exception as e3:
            print("e1:", e, "e2:", e2, "e3:", e3)
            sys.exit(1)

cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT count(*) as cnt FROM document_processing_queue")
cnt = cur.fetchone()["cnt"]
print(f"DOCUMENT_PROCESSING_QUEUE COUNT IN LOCAL document_intelligence DB = {cnt}")

cur.execute("SELECT count(*) as cnt FROM document_match_details")
cnt_matches = cur.fetchone()["cnt"]
print(f"DOCUMENT_MATCH_DETAILS COUNT IN LOCAL document_intelligence DB = {cnt_matches}")

conn.close()

PYEOF
