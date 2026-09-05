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

_, _, crm_db, _ = connect_databases()

sql_expr = """
    CASE 
      WHEN jsonb_typeof(payload -> 'expert_category_scope') = 'object' 
      THEN payload -> 'expert_category_scope' ->> 'verdict' 
      ELSE payload ->> 'expert_category_scope' 
    END
"""

rows = crm_db.execute_query(f"""
    SELECT id, procurement_id, {sql_expr} AS scope
    FROM crm_v3_expert_annotations 
    WHERE is_current = TRUE AND (id=31 OR id=32)
""")
for r in rows:
    print(f"ID={r['id']} scope={repr(r['scope'])}")
PYEOF
