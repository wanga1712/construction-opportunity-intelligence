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
from src.ui.components.analytics_v2.tabs import _stage_workset_ids
from src.services.annotation_state_service import count_annotation_states_sql, load_current_annotation_states

_, _, crm_db, _ = connect_databases()

workset_ids = _stage_workset_ids("torgi")
print(f"Total workset_ids: {len(workset_ids)}")

rows = crm_db.execute_query(
    """SELECT id, procurement_id, annotation_version, created_at, payload
       FROM crm_v3_expert_annotations
       WHERE is_current = TRUE AND procurement_id = ANY(%s)""",
    (workset_ids,),
)
print(f"Current expert annotations in workset: {len(rows)}")

for r in rows:
    print(f"ID={r['id']}, proc_id={r['procurement_id']}, payload={json.dumps(r['payload'], ensure_ascii=False)}")

print("\n--- SQL COUNTS ---")
sql_counts = count_annotation_states_sql(workset_ids, crm_db)
print("sql_counts:", sql_counts)

print("\n--- PYTHON COUNTS (via load_current_annotation_states for existing rows) ---")
annotated_pids = [r['procurement_id'] for r in rows]
if annotated_pids:
    py_states = load_current_annotation_states(annotated_pids, crm_db)
    for pid, state in py_states.items():
        print(f"PID={pid}: is_reviewed={state.get('is_reviewed')}, is_staged_complete={state.get('is_staged_complete')}, category_scope={state.get('expert_category_scope')}, comm_entry={state.get('expert_commercial_entry')}, legacy={state.get('is_legacy_negative')}")

PYEOF
