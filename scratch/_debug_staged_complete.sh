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
from src.services.annotation_category_gate import category_scope_of, is_legacy_negative_payload
from src.services.annotation_staged import is_staged_complete, has_object_classification
from src.services.expert_procurement_mode import procurement_mode_of

_, _, crm_db, _ = connect_databases()

rows = crm_db.execute_query("SELECT id, procurement_id, payload FROM crm_v3_expert_annotations WHERE is_current = TRUE")
for r in rows:
    p = r["payload"] or {}
    sc = category_scope_of(p)
    ho = has_object_classification(p)
    pm = procurement_mode_of(p)
    sc_comp = is_staged_complete(p)
    leg = is_legacy_negative_payload(p)
    print(f"ID={r['id']} PID={r['procurement_id']}: scope={sc}, has_obj={ho}, proc_mode={pm}, staged_complete={sc_comp}, legacy={leg}")

PYEOF
