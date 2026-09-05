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
from src.services.annotation_category_gate import category_scope_of, is_legacy_negative_payload
from src.services.expert_commercial_entry import commercial_entry_of
from src.services.expert_medal_stage import medal_of

_, _, crm_db, _ = connect_databases()

workset_ids = _stage_workset_ids("torgi")
print(f"=== DB TRUTH FOR TORGI WORKSET (Total: {len(workset_ids)}) ===")

rows = crm_db.execute_query("""
    SELECT id, procurement_id, payload
    FROM crm_v3_expert_annotations
    WHERE is_current = TRUE AND procurement_id = ANY(%s)
""", (workset_ids,))

ws_set = set(workset_ids)
ws_total = len(workset_ids)

in_cat = 0
out_cat = 0
uncert = 0
comm = 0
non_comm = 0
legacy_ni = 0
staged_reviewed = 0
any_reviewed = 0

gold = 0
silver = 0
bronze = 0
wood = 0

for r in rows:
    p = r["payload"] or {}
    sc = category_scope_of(p)
    ce = commercial_entry_of(p)
    leg = is_legacy_negative_payload(p)
    med = medal_of(p)
    
    if sc == "IN_CATEGORY": in_cat += 1
    elif sc == "OUT_OF_CATEGORY": out_cat += 1
    elif sc == "UNCERTAIN": uncert += 1
    
    if ce == "COMMERCIAL": comm += 1
    elif ce == "NON_COMMERCIAL": non_comm += 1
    
    if leg: legacy_ni += 1
    
    if sc in ("IN_CATEGORY", "OUT_OF_CATEGORY", "UNCERTAIN"):
        staged_reviewed += 1
        any_reviewed += 1
    elif leg:
        any_reviewed += 1
        
    if med == "GOLD": gold += 1
    elif med == "SILVER": silver += 1
    elif med == "BRONZE": bronze += 1
    elif med == "WOOD": wood += 1

print("Definition 1 (Reviewed = staged + legacy):")
print(f"  DB_WORKSET_TOTAL={ws_total}")
print(f"  DB_REVIEWED={any_reviewed}")
print(f"  DB_UNREVIEWED={ws_total - any_reviewed}")
print(f"  DB_IN_CATEGORY={in_cat}")
print(f"  DB_OUT_OF_CATEGORY={out_cat}")
print(f"  DB_UNCERTAIN={uncert}")
print(f"  DB_COMMERCIAL={comm}")
print(f"  DB_NON_COMMERCIAL={non_comm}")
print(f"  DB_LEGACY_NOT_INTERESTING={legacy_ni}")

print("\nDefinition 2 (Reviewed = staged only):")
print(f"  DB_WORKSET_TOTAL={ws_total}")
print(f"  DB_REVIEWED={staged_reviewed}")
print(f"  DB_UNREVIEWED={ws_total - staged_reviewed}")
print(f"  DB_IN_CATEGORY={in_cat}")
print(f"  DB_OUT_OF_CATEGORY={out_cat}")
print(f"  DB_UNCERTAIN={uncert}")
print(f"  DB_COMMERCIAL={comm}")
print(f"  DB_NON_COMMERCIAL={non_comm}")
print(f"  DB_LEGACY_NOT_INTERESTING={legacy_ni}")

print("\n=== TOTAL CURRENT HUMAN ANNOTATIONS IN DB (ALL TABLES/STAGES) ===")
all_rows = crm_db.execute_query("""
    SELECT id, procurement_id, payload
    FROM crm_v3_expert_annotations
    WHERE is_current = TRUE
""")

all_total = len(all_rows)
all_in_cat = 0
all_out_cat = 0
all_uncert = 0
all_comm = 0
all_non_comm = 0
all_legacy_ni = 0
all_reviewed = 0
all_gold = 0
all_silver = 0
all_bronze = 0
all_wood = 0

for r in all_rows:
    p = r["payload"] or {}
    sc = category_scope_of(p)
    ce = commercial_entry_of(p)
    leg = is_legacy_negative_payload(p)
    med = medal_of(p)
    
    if sc == "IN_CATEGORY": all_in_cat += 1
    elif sc == "OUT_OF_CATEGORY": all_out_cat += 1
    elif sc == "UNCERTAIN": all_uncert += 1
    
    if ce == "COMMERCIAL": all_comm += 1
    elif ce == "NON_COMMERCIAL": all_non_comm += 1
    
    if leg: all_legacy_ni += 1
    
    if sc in ("IN_CATEGORY", "OUT_OF_CATEGORY", "UNCERTAIN") or leg:
        all_reviewed += 1
        
    if med == "GOLD": all_gold += 1
    elif med == "SILVER": all_silver += 1
    elif med == "BRONZE": all_bronze += 1
    elif med == "WOOD": all_wood += 1

print(f"TOTAL_CURRENT_HUMAN_ANNOTATIONS={all_total}")
print(f"REVIEWED_PROCUREMENTS={all_reviewed}")
print(f"IN_CATEGORY={all_in_cat}")
print(f"OUT_OF_CATEGORY={all_out_cat}")
print(f"UNCERTAIN={all_uncert}")
print(f"COMMERCIAL={all_comm}")
print(f"NON_COMMERCIAL={all_non_comm}")
print(f"MEDAL_GOLD={all_gold}")
print(f"MEDAL_SILVER={all_silver}")
print(f"MEDAL_BRONZE={all_bronze}")
print(f"MEDAL_WOOD={all_wood}")
print(f"LEGACY_NOT_INTERESTING={all_legacy_ni}")

PYEOF
