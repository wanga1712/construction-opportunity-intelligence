#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import os, sys
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')
from src.services.db_bootstrap import connect_databases
from src.ui.components.analytics_v2.tabs import _stage_workset_ids

_, _, crm_db, _ = connect_databases()

workset_ids = _stage_workset_ids("torgi")

rows = crm_db.execute_query("""
    SELECT source_table, count(*)
    FROM crm_procurements
    WHERE id = ANY(%s)
    GROUP BY source_table
""", (workset_ids,))

counts = {r['source_table']: r['count'] for r in rows}
print("Source table counts in Торги workset:")
for k, v in counts.items():
    print(f"  {k}: {v}")

cnt_44 = counts.get('reestr_contract_44_fz', 0)
cnt_223 = counts.get('reestr_contract_223_fz', 0)
cnt_all = len(workset_ids)

print(f"\nDB_ALL={cnt_all}")
print(f"DB_44={cnt_44}")
print(f"DB_223={cnt_223}")
print(f"DB_ALL == DB_44 + DB_223: {cnt_all == cnt_44 + cnt_223}")

PYEOF
