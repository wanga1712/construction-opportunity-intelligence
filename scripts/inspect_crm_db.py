import os
import sys
sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv("/opt/CRM_Streamlit/.env")

import psycopg2
import json
from src.services.crm_db_runtime import require_crm_db_connect_kwargs

conn = psycopg2.connect(**require_crm_db_connect_kwargs())
with conn.cursor() as cur:
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
    tables = [r[0] for r in cur.fetchall()]
    print("CRM DB Tables:", tables)
    
    # Check crm_procurements columns
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='crm_procurements'")
    proc_cols = cur.fetchall()
    print("\ncrm_procurements columns:", [c[0] for c in proc_cols])

    # Check crm_category_candidates columns
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='crm_category_candidates'")
    cand_cols = cur.fetchall()
    print("\ncrm_category_candidates columns:", [c[0] for c in cand_cols])
    
    # Check crm_procurement_category_opportunities columns
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='crm_procurement_category_opportunities'")
    opp_cols = cur.fetchall()
    print("\ncrm_procurement_category_opportunities columns:", [c[0] for c in opp_cols])

    # Check procurement_ai_assessments columns
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='procurement_ai_assessments'")
    ai_cols = cur.fetchall()
    print("\nprocurement_ai_assessments columns:", [c[0] for c in ai_cols])
conn.close()
