#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import os, sys, psycopg2, psycopg2.extras
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')
from src.services.commercial_routing_v3.queue_producer import _load_doc_env

_load_doc_env()
conn_str = os.environ.get("S13_DOCUMENT_INTELLIGENCE_URL") or os.environ.get("DOCUMENT_INTELLIGENCE_URL")
if not conn_str:
    conn_str = "postgresql://postgres:postgres@localhost:5432/s13_document_intelligence"

conn = psycopg2.connect(conn_str)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

cur.execute("""
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_name = 'document_processing_queue'
    ORDER BY ordinal_position
""")
cols = cur.fetchall()
print("=== DOCUMENT_PROCESSING_QUEUE COLUMNS ===")
for c in cols:
    print(f"  {c['column_name']}: {c['data_type']}")

cur.execute("""
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_name = 'document_observations'
    ORDER BY ordinal_position
""")
obs_cols = cur.fetchall()
print("\n=== DOCUMENT_OBSERVATIONS COLUMNS ===")
for c in obs_cols:
    print(f"  {c['column_name']}: {c['data_type']}")

conn.close()
PYEOF
