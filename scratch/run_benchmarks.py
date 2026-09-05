import time
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, "/opt/pythonProject89")

from src.services.db_bootstrap import connect_crm_database
from src.services.annotation_state_service import (
    count_annotation_states_sql,
    count_law_states_sql,
    filter_workset_ids_by_law,
    filter_workset_ids_sql,
)
from src.services.commercial_routing_v3.research_ui_projection import (
    load_research_filter_index,
    load_research_ui_projection,
)

print("Running E2E DB Benchmarks...")
t0 = time.time()
crm_db = connect_crm_database()
t1 = time.time()
print(f"connect_crm_database: {t1 - t0:.4f} seconds")

# Use execute_query on crm_db instance
rows = crm_db.execute_query("SELECT id FROM crm_procurements WHERE crm_stage = 'torgi'")
workset_ids = [r["id"] for r in rows]
print(f"Workset IDs count: {len(workset_ids)}")

t0 = time.time()
law_counts = count_law_states_sql(workset_ids, crm_db)
t1 = time.time()
print(f"count_law_states_sql: {t1 - t0:.4f} seconds")

t0 = time.time()
law_workset_ids = filter_workset_ids_by_law(workset_ids, "ALL", crm_db)
t1 = time.time()
print(f"filter_workset_ids_by_law: {t1 - t0:.4f} seconds")

t0 = time.time()
sql_counts = count_annotation_states_sql(law_workset_ids, crm_db)
t1 = time.time()
print(f"count_annotation_states_sql: {t1 - t0:.4f} seconds")

t0 = time.time()
filtered_workset_ids = filter_workset_ids_sql(law_workset_ids, "ALL", crm_db)
t1 = time.time()
print(f"filter_workset_ids_sql: {t1 - t0:.4f} seconds")

t0 = time.time()
projections = load_research_filter_index(filtered_workset_ids, crm_db)
t1 = time.time()
print(f"load_research_filter_index (lightweight, 4867 IDs): {t1 - t0:.4f} seconds")

t0 = time.time()
page_ids = filtered_workset_ids[:25]
page_projections = load_research_ui_projection(page_ids, crm_db)
t1 = time.time()
print(f"load_research_ui_projection (heavy, 25 IDs): {t1 - t0:.4f} seconds")
