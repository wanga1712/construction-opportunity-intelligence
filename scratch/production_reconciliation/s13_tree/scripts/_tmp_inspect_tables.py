#!/usr/bin/env python3
import sys

sys.path[:0] = ["/opt/CRM_Streamlit", "/opt/pythonProject89"]
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")
from src.services.db_bootstrap import connect_databases

_r, tender_db, crm_db, _w = connect_databases()
for tname in [
    "crm_category_opportunity_medal_history",
    "crm_sync_runs",
    "crm_procurement_sync_log",
]:
    n = crm_db.execute_scalar("SELECT to_regclass(%s)", (f"public.{tname}",))
    print(tname, n)
rows = (
    crm_db.execute_query(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema='public'
          AND (table_name ILIKE '%sync%' OR table_name ILIKE '%medal%' OR table_name ILIKE '%history%')
        ORDER BY 1
        """
    )
    or []
)
print("tables:", ", ".join(r["table_name"] for r in rows))
