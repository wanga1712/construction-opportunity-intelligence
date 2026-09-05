import sys
sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, "/opt/CRM_Streamlit_rescue")

import json
from src.services.db_bootstrap import connect_databases
from src.services.annotation_state_service import count_law_states_sql, filter_workset_ids_by_law, count_annotation_states_sql, filter_workset_ids_sql
from src.services.commercial_routing_v3.research_ui_projection import load_research_ui_projection, filter_research_workset_ids

_, _, crm_db, _ = connect_databases()

# Load master workset IDs
rows = crm_db.execute_query("SELECT id FROM crm_procurements WHERE crm_stage='torgi' AND award_status='submission_open' ORDER BY id DESC")
master_ids = [r["id"] for r in (rows or [])]

# 1. Upstream law filter (ALL)
law_counts = count_law_states_sql(master_ids, crm_db)
law_ids = filter_workset_ids_by_law(master_ids, "ALL", crm_db)

# 2. Upstream expert review filter (ALL)
expert_counts = count_annotation_states_sql(law_ids, crm_db)
expert_ids = filter_workset_ids_sql(law_ids, "ALL", crm_db)

# 3. Bulk research projection before pagination
projections = load_research_ui_projection(expert_ids, crm_db)

# Count research states
r_counts = {}
for proj in projections.values():
    st_val = proj.research_state
    r_counts[st_val] = r_counts.get(st_val, 0) + 1
r_counts["ALL"] = len(projections)

print("=== RESEARCH STATES FOR WORKSET ===")
print(json.dumps(r_counts, indent=2))

# 4. Test filtering by EVIDENCE_FOUND
ev_ids = filter_research_workset_ids(expert_ids, projections, selected_research="EVIDENCE_FOUND")
print(f"EVIDENCE_FOUND count: {len(ev_ids)}, IDs: {ev_ids[:10]}")

# 5. Test filtering by NO_EVIDENCE
no_ev_ids = filter_research_workset_ids(expert_ids, projections, selected_research="NO_EVIDENCE")
print(f"NO_EVIDENCE count: {len(no_ev_ids)}, IDs: {no_ev_ids[:10]}")

# 6. Test Category Filter (if any category present)
cat_counts = {}
for proj in projections.values():
    for c in proj.category_names:
        cat_counts[c] = cat_counts.get(c, 0) + 1

print("=== CATEGORY COUNTS ===")
print(json.dumps(cat_counts, indent=2))

cat_test_name = list(cat_counts.keys())[0] if cat_counts else "ALL"
cat_ids = filter_research_workset_ids(expert_ids, projections, selected_category=cat_test_name)
print(f"CATEGORY '{cat_test_name}' count: {len(cat_ids)}, IDs: {cat_ids[:10]}")

# 7. Test Composition: Expert review = UNREVIEWED + Research = EVIDENCE_FOUND
unreviewed_ids = filter_workset_ids_sql(law_ids, "UNREVIEWED", crm_db)
unreviewed_projs = load_research_ui_projection(unreviewed_ids, crm_db)
comp_ids = filter_research_workset_ids(unreviewed_ids, unreviewed_projs, selected_research="EVIDENCE_FOUND")
print(f"COMPOSITION (UNREVIEWED + EVIDENCE_FOUND) count: {len(comp_ids)}, IDs: {comp_ids[:10]}")
