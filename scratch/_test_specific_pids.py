import sys
sys.path.insert(0, "/opt/CRM_Streamlit_rescue")

import psycopg2, psycopg2.extras, json
from src.services.db_bootstrap import connect_databases
from src.services.commercial_routing_v3.research_ui_projection import load_research_ui_projection

_, _, crm_db, _ = connect_databases()

pids = [160646, 160648, 160650, 160658, 160660, 150194, 149969]
projs = load_research_ui_projection(pids, crm_db)

out = {}
for pid, p in projs.items():
    out[pid] = {
        "procurement_id": p.procurement_id,
        "research_state": p.research_state,
        "documents_total": p.documents_total,
        "evidence_count": p.evidence_count,
        "category_names": p.category_names,
    }

print("=== SPECIFIC PIDS PROJECTION THROUGH CRM_DB ===")
print(json.dumps(out, indent=2))
