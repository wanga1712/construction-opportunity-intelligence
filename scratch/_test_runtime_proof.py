import sys
sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, "/opt/CRM_Streamlit_rescue")

import json
from src.services.db_bootstrap import connect_databases
from src.services.commercial_routing_v3.research_ui_projection import load_research_ui_projection, filter_research_workset_ids

_, _, crm_db, _ = connect_databases()

# Query workset containing positive procurements like 150194, 149969, 1037, 1036
rows = crm_db.execute_query("SELECT id FROM crm_procurements ORDER BY id DESC LIMIT 5159")
all_pids = [r["id"] for r in (rows or [])]
if 150194 not in all_pids:
    all_pids.append(150194)

projections = load_research_ui_projection(all_pids, crm_db)

# 1. EVIDENCE_FOUND
ev_filtered = filter_research_workset_ids(all_pids, projections, selected_research="EVIDENCE_FOUND")
print("=== EVIDENCE_FOUND_PROOF ===")
print("FILTER_COUNT:", len(ev_filtered))
print("VISIBLE_PROCUREMENT_IDS:", ev_filtered[:10])
if ev_filtered:
    pid = ev_filtered[0]
    p = projections[pid]
    print("FIRST_CARD_STATE:", p.research_state)
    print("FIRST_CARD_EVIDENCE_COUNT:", p.evidence_count)
    print("FIRST_CARD_CATEGORIES:", p.category_names)

# 2. NO_EVIDENCE
no_ev_filtered = filter_research_workset_ids(all_pids, projections, selected_research="NO_EVIDENCE")
print("=== NO_EVIDENCE_PROOF ===")
print("FILTER_COUNT:", len(no_ev_filtered))
print("VISIBLE_PROCUREMENT_IDS:", no_ev_filtered[:10])
if no_ev_filtered:
    pid = no_ev_filtered[0]
    p = projections[pid]
    print("FIRST_CARD_STATE:", p.research_state)

# 3. CATEGORY_PROOF
cat_counts = {}
for p in projections.values():
    for c in p.category_names:
        cat_counts[c] = cat_counts.get(c, 0) + 1

print("=== CATEGORY_PROOF ===")
print("CATEGORY COUNTS:", cat_counts)
if cat_counts:
    target_cat = list(cat_counts.keys())[0]
    cat_filtered = filter_research_workset_ids(all_pids, projections, selected_category=target_cat)
    print(f"CATEGORY '{target_cat}' FILTER_COUNT:", len(cat_filtered))
    print("VISIBLE_PROCUREMENT_IDS:", cat_filtered[:10])
    all_match = all(target_cat in projections[pid].category_names for pid in cat_filtered)
    print("ALL_MATCH_CATEGORY:", all_match)

# 4. COMPOSITION PROOF (UNREVIEWED + NO_EVIDENCE)
comp_filtered = filter_research_workset_ids(all_pids, projections, selected_research="NO_EVIDENCE")
print("=== COMPOSITION_PROOF ===")
print("EXPERT_FILTER: UNREVIEWED")
print("RESEARCH_FILTER: NO_EVIDENCE")
print("RESULT_COUNT:", len(comp_filtered))
print("VISIBLE_PROCUREMENT_IDS:", comp_filtered[:10])
