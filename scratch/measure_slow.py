import time
import os
import sys

# Add repository root to path
sys.path.insert(0, "/opt/CRM_Streamlit")

from src.services.commercial_routing_v3.research_ui_projection import load_research_ui_projection, _get_crm_db_conn

print("Starting measurement script...")
crm_conn = _get_crm_db_conn()
cur = crm_conn.cursor()
cur.execute("SELECT id FROM crm_procurements ORDER BY id DESC LIMIT 5000")
ids = [r[0] for r in cur.fetchall()]
crm_conn.close()

print(f"Loaded {len(ids)} procurement IDs from CRM DB")

t0 = time.time()
# Mock crm_db to force load_research_ui_projection to open database connections itself
projections = load_research_ui_projection(ids, None)
t1 = time.time()

print(f"load_research_ui_projection took {t1 - t0:.4f} seconds for {len(ids)} IDs")
