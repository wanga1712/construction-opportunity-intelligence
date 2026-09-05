#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import os, sys, json
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

print("=== ALL ROWS IN crm_v3_expert_annotations ===")
cur.execute("SELECT id, procurement_id, is_current, decision_source, created_by, created_at, payload FROM crm_v3_expert_annotations ORDER BY id")
rows = cur.fetchall()
print(f"Total annotations in table: {len(rows)}")
for r in rows:
    print(f"ID={r[0]}, proc_id={r[1]}, is_current={r[2]}, source={r[3]}, created_by={r[4]}, created_at={r[5]}")
    print(f"   payload={json.dumps(r[6], ensure_ascii=False)}")

print("\n=== CHECK crm_manual_category_overrides ===")
try:
    cur.execute("SELECT COUNT(*) FROM crm_manual_category_overrides")
    print("crm_manual_category_overrides count:", cur.fetchone()[0])
except Exception as e:
    print("crm_manual_category_overrides err:", e)

print("\n=== CHECK crm_manual_overrides ===")
try:
    cur.execute("SELECT COUNT(*) FROM crm_manual_overrides")
    print("crm_manual_overrides count:", cur.fetchone()[0])
except Exception as e:
    print("crm_manual_overrides err:", e)

print("\n=== CHECK crm_procurements manual_override AND crm_stage ===")
cur.execute("SELECT COUNT(*) FROM crm_procurements WHERE manual_override IS NOT NULL AND manual_override != '' AND manual_override != '{}'")
print("crm_procurements manual_override non-empty count:", cur.fetchone()[0])

conn.close()
PYEOF
