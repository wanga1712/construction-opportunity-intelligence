#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import os, sys, json
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')
from src.services.db_bootstrap import connect_databases

_, _, crm_db, _ = connect_databases()

rows = crm_db.execute_query("""
    SELECT id, procurement_id, 
           payload ->> 'expert_category_scope' AS s1,
           payload -> 'expert_category_scope' ->> 'verdict' AS s2,
           COALESCE(payload ->> 'expert_category_scope', payload -> 'expert_category_scope' ->> 'verdict') AS s3,
           payload
    FROM crm_v3_expert_annotations 
    WHERE is_current = TRUE AND (id=31 OR id=32)
""")
for r in rows:
    print(f"ID={r['id']} PID={r['procurement_id']} s1={repr(r['s1'])} s2={repr(r['s2'])} s3={repr(r['s3'])}")
    print("  payload:", r["payload"])
PYEOF
