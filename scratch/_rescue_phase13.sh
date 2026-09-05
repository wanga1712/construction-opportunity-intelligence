#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== PHASE 13: LAW FILTER DB PARITY ==="
PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import os, sys
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')
import psycopg2
conn = psycopg2.connect(
    host=os.environ.get('CRM_DB_HOST','127.0.0.1'),
    port=int(os.environ.get('CRM_DB_PORT',5432)),
    dbname=os.environ.get('CRM_DB_DATABASE','crm'),
    user=os.environ.get('CRM_DB_USER','crm_app'),
    password=os.environ.get('CRM_DB_PASSWORD',''))
conn.autocommit=True
cur=conn.cursor()

# Find source_table values and map to laws
cur.execute("""
    SELECT source_table, COUNT(*)
    FROM crm_procurements
    WHERE crm_stage = 'torgi' AND award_status = 'submission_open'
    GROUP BY source_table ORDER BY source_table
""")
print("=== SOURCE_TABLE DISTRIBUTION (torgi + submission_open) ===")
for r in cur.fetchall():
    print(f"  {r[0]} = {r[1]}")

# The law filter in the workset is done via source_table:
# 44-ФЗ = source_table containing 'fz44' or '44_fz' or similar
# 223-ФЗ = source_table containing '223'
# 615-ПП = source_table containing '615'
# Let's check the submission window SQL to see exact filter
cur.execute("""
    SELECT source_table, COUNT(*)
    FROM crm_procurements
    WHERE crm_stage = 'torgi' AND award_status = 'submission_open'
      AND end_date > now()
    GROUP BY source_table ORDER BY source_table
""")
print("=== WITH end_date > now() ===")
total = 0
for r in cur.fetchall():
    print(f"  {r[0]} = {r[1]}")
    total += r[1]
print(f"  TOTAL = {total}")

# Overall active torgi
cur.execute("""
    SELECT COUNT(*)
    FROM crm_procurements
    WHERE crm_stage = 'torgi' AND award_status = 'submission_open'
""")
print(f"DB_ALL_TORGI_SUBMISSION_OPEN={cur.fetchone()[0]}")

conn.close()
PYEOF

echo "--- Check submission_window module ---"
grep -n 'actionable_submission_sql\|def actionable' src/services/commercial_routing_v3/submission_window.py 2>/dev/null | head -5
cat src/services/commercial_routing_v3/submission_window.py

echo "PHASE_13=DONE"
