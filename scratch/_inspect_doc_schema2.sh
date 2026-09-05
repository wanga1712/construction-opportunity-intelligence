#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import os, sys, psycopg2, psycopg2.extras
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')
from src.services.commercial_routing_v3.autonomous_learning_loop import HunterAuditorOrchestrator
from src.services.db_bootstrap import connect_databases

_, _, crm_db, _ = connect_databases()
orch = HunterAuditorOrchestrator(crm_db)
conn = orch._get_doc_conn()
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
    WHERE table_name = 'document_match_details'
    ORDER BY ordinal_position
""")
obs_cols = cur.fetchall()
print("\n=== DOCUMENT_MATCH_DETAILS COLUMNS ===")
for c in obs_cols:
    print(f"  {c['column_name']}: {c['data_type']}")

conn.close()
PYEOF
