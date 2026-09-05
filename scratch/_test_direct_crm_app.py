import sys
sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, "/opt/CRM_Streamlit_rescue")

import psycopg2, psycopg2.extras, json
from src.services.db_bootstrap import connect_databases
from src.services.commercial_routing_v3.research_ui_projection import load_research_ui_projection

_, _, crm_db_bootstrap, _ = connect_databases()

# Query recent 5159 procurements as loaded by stage workspace feeds
rows = crm_db_bootstrap.execute_query("SELECT id FROM crm_procurements ORDER BY id DESC LIMIT 5159")
all_ids = [r["id"] for r in (rows or [])]

print(f"LOADED {len(all_ids)} PIDS FROM CRM_PROCUREMENTS")

projections = load_research_ui_projection(all_ids, crm_db_bootstrap)

counts = {
    "ALL": len(projections),
    "EVIDENCE_FOUND": 0,
    "NO_EVIDENCE": 0,
    "RESEARCHING": 0,
    "PARTIAL": 0,
    "FAILED": 0,
    "WAITING_RESEARCH": 0,
}

for proj in projections.values():
    st_val = proj.research_state
    if st_val in counts:
        counts[st_val] += 1

counts["SUM"] = sum(v for k, v in counts.items() if k not in ("ALL", "SUM"))

print("=== ACTUAL CRM RUNTIME COUNTS WITH DIRECT CRM_APP AUTHORITY ===")
print(json.dumps(counts, indent=2))
