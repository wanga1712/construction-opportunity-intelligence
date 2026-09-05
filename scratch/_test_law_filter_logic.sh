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
from src.services.annotation_state_service import count_annotation_states_sql, filter_workset_ids_sql

_, _, crm_db, _ = connect_databases()
workset_ids = _stage_workset_ids("torgi")

def count_law_states_sql(procurement_ids: list[int], crm_db) -> dict[str, int]:
    if not procurement_ids:
        return {"ALL": 0, "44-ФЗ": 0, "223-ФЗ": 0}
    rows = crm_db.execute_query(
        "SELECT source_table, count(*) AS cnt FROM crm_procurements WHERE id = ANY(%s) GROUP BY source_table",
        (procurement_ids,),
    )
    c44 = 0
    c223 = 0
    for r in (rows or []):
        stbl = r.get("source_table")
        cnt = int(r.get("cnt") or 0)
        if stbl == "reestr_contract_44_fz":
            c44 = cnt
        elif stbl == "reestr_contract_223_fz":
            c223 = cnt
    return {
        "ALL": len(procurement_ids),
        "44-ФЗ": c44,
        "223-ФЗ": c223,
    }

def filter_workset_ids_by_law(procurement_ids: list[int], selected_law: str, crm_db) -> list[int]:
    if not procurement_ids or selected_law == "ALL":
        return procurement_ids
    if selected_law == "44-ФЗ":
        source_tbl = "reestr_contract_44_fz"
    elif selected_law == "223-ФЗ":
        source_tbl = "reestr_contract_223_fz"
    else:
        return procurement_ids
        
    rows = crm_db.execute_query(
        "SELECT id FROM crm_procurements WHERE id = ANY(%s) AND source_table = %s",
        (procurement_ids, source_tbl),
    )
    matching = set(r["id"] for r in (rows or []))
    return [pid for pid in procurement_ids if pid in matching]

law_counts = count_law_states_sql(workset_ids, crm_db)
print("LAW COUNTS:", law_counts)
assert law_counts["ALL"] == law_counts["44-ФЗ"] + law_counts["223-ФЗ"], "Invariant ALL == 44 + 223 failed"

ids_all = filter_workset_ids_by_law(workset_ids, "ALL", crm_db)
ids_44 = filter_workset_ids_by_law(workset_ids, "44-ФЗ", crm_db)
ids_223 = filter_workset_ids_by_law(workset_ids, "223-ФЗ", crm_db)

print(f"len(ids_all)={len(ids_all)}")
print(f"len(ids_44)={len(ids_44)}")
print(f"len(ids_223)={len(ids_223)}")

assert len(ids_all) == law_counts["ALL"]
assert len(ids_44) == law_counts["44-ФЗ"]
assert len(ids_223) == law_counts["223-ФЗ"]

# Test composition with review filter
rev_counts_44 = count_annotation_states_sql(ids_44, crm_db)
print("\nREVIEW COUNTS FOR 44-ФЗ:", rev_counts_44)

ids_44_unrev = filter_workset_ids_sql(ids_44, "UNREVIEWED", crm_db)
print(f"44-ФЗ + UNREVIEWED count={len(ids_44_unrev)}")
assert len(ids_44_unrev) == rev_counts_44["UNREVIEWED"]

print("\nALL LAW FILTER SQL LOGIC TEST PASSED 100%!")
PYEOF
