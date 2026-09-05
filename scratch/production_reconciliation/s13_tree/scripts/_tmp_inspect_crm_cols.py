#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path[:0] = ["/opt/CRM_Streamlit", "/opt/pythonProject89"]
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")
from src.services.db_bootstrap import connect_databases

_r, tender_db, crm_db, _w = connect_databases()
for t in [
    "crm_procurements",
    "crm_procurement_category_opportunities",
    "crm_v3_inference_attempts",
    "crm_medal_history",
    "crm_procurement_sync_runs",
]:
    rows = (
        crm_db.execute_query(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=%s
            ORDER BY ordinal_position
            """,
            (t,),
        )
        or []
    )
    print("---", t, "---")
    print(", ".join(r["column_name"] for r in rows) if rows else "MISSING")
