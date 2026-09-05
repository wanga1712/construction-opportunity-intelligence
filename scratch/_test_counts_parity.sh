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
from src.services.annotation_state_service import count_annotation_states_sql, annotation_state_counts, load_current_annotation_states

_, _, crm_db, _ = connect_databases()

# Get all procurement_ids from crm_v3_expert_annotations
rows = crm_db.execute_query("SELECT procurement_id FROM crm_v3_expert_annotations WHERE is_current = TRUE")
pids = [r["procurement_id"] for r in rows]

py_states = load_current_annotation_states(pids, crm_db)
py_counts = annotation_state_counts(py_states)
sql_counts = count_annotation_states_sql(pids, crm_db)

print("=== ALL 20 ANNOTATIONS PIDS ===")
print("PY COUNTS: ", py_counts)
print("SQL COUNTS:", sql_counts)
print("PARITY MATCH:", py_counts == sql_counts)
if py_counts != sql_counts:
    for k in py_counts:
        if py_counts[k] != sql_counts.get(k):
            print(f"  DIFF {k}: PY={py_counts[k]} vs SQL={sql_counts.get(k)}")

PYEOF
