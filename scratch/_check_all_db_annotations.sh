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
    SELECT a.id, a.procurement_id, a.is_current, a.created_by, a.created_at, p.crm_stage, p.award_status, a.payload
    FROM crm_v3_expert_annotations a
    LEFT JOIN crm_procurements p ON p.id = a.procurement_id
    WHERE a.is_current = TRUE
    ORDER BY a.id
""")
print(f"Total current annotations in DB: {len(rows)}")
for r in rows:
    p_id = r['procurement_id']
    stage = r.get('crm_stage')
    award = r.get('award_status')
    payload = r.get('payload') or {}
    scope = payload.get('expert_category_scope')
    comm = payload.get('expert_commercial_entry')
    medal = payload.get('expert_medal')
    print(f"ID={r['id']} PID={p_id} stage={stage} award={award} scope={scope} comm={comm} medal={medal} created_by={r['created_by']}")

PYEOF
