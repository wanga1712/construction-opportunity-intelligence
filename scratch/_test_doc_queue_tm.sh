#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os, psycopg2, psycopg2.extras
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

from src.services.commercial_routing_v3.queue_producer import _load_doc_env
_load_doc_env()

dsn = {
    "host": os.getenv("S13_DOCUMENT_DB_HOST", "10.8.0.7"),
    "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
    "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "tender_monitor"),
    "user": os.getenv("S13_DOCUMENT_DB_USER", "postgres"),
    "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", "oTIg3EqK85pux8SfZTuCbS-bEcObXiGfV3P2hU2m5uJ_pYMbRtRmP8jnMA-hvyhR"),
}

conn = psycopg2.connect(**dsn)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

cur.execute("SELECT count(*) as cnt FROM document_processing_queue")
cnt = cur.fetchone()["cnt"]
print(f"DOCUMENT_PROCESSING_QUEUE COUNT IN tender_monitor = {cnt}")

cur.execute("SELECT count(*) as cnt FROM document_match_details")
cnt_matches = cur.fetchone()["cnt"]
print(f"DOCUMENT_MATCH_DETAILS COUNT IN tender_monitor = {cnt_matches}")

conn.close()

PYEOF
