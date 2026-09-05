#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')

from src.services.commercial_routing_v3.factual_feeder import _get_doc_db_conn
from src.services.db_bootstrap import connect_databases

conn = _get_doc_db_conn()
cur = conn.cursor()

cur.execute("""
    SELECT f.procurement_id, count(DISTINCT f.id) as files_count, count(DISTINCT e.id) as evidence_count
    FROM document_files f
    LEFT JOIN document_evidence e ON e.procurement_id = f.procurement_id
    GROUP BY f.procurement_id
    HAVING count(DISTINCT f.id) > 0
    ORDER BY f.procurement_id DESC
    LIMIT 20
""")

rows = cur.fetchall()
print("PROCUREMENTS WITH PARSED DOCS AND EVIDENCE IN document_intelligence:")
for r in rows:
    print(f"  procurement_id={r[0]}, files={r[1]}, evidence={r[2]}")

conn.close()

PYEOF
