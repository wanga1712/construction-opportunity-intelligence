#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import os, sys
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')
from src.services.db_bootstrap import connect_databases

tender_db, radar_db, crm_db, _ = connect_databases()

print("=== CHECKING CRM DB TABLES ===")
tables = crm_db.execute_query("""
    SELECT table_name 
    FROM information_schema.tables 
    WHERE table_schema = 'public' 
    ORDER BY table_name
""")
table_names = [t['table_name'] for t in tables]
for t in table_names:
    if any(k in t for k in ['doc', 'queue', 'finding', 'evidence', 'assess', 'research', 'learning', 'trade', 'procure']):
        print(f"  TABLE: {t}")

print("\n=== CHECKING TENDER DB TABLES ===")
t_tables = tender_db.execute_query("""
    SELECT table_name 
    FROM information_schema.tables 
    WHERE table_schema = 'public' 
    ORDER BY table_name
""")
t_table_names = [t['table_name'] for t in t_tables]
for t in t_table_names:
    if any(k in t for k in ['doc', 'file', 'attachment', 'match', 'parse', 'procure']):
        print(f"  TENDER TABLE: {t}")

PYEOF
