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

print("=== TABLE COLUMNS ===")
cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='crm_v3_expert_annotations'")
for r in cur.fetchall():
    print(f"  {r[0]} ({r[1]})")

print("\n=== PAYLOAD KEYS ===")
cur.execute("SELECT payload FROM crm_v3_expert_annotations WHERE is_current = TRUE LIMIT 20")
payload_keys = set()
for r in cur.fetchall():
    if r[0]:
        payload_keys.update(r[0].keys())
print("Payload keys:", sorted(payload_keys))

print("\n=== PAYLOAD JSONB QUERIES ===")
cur.execute("""
    SELECT 
        payload->>'expert_category_scope' AS cat_scope,
        payload->>'expert_scope_verdict' AS scope_verdict,
        payload->>'expert_commercial_verdict' AS comm_verdict,
        payload->>'expert_commercial_entry' AS comm_entry,
        payload->>'expert_medal' AS medal,
        COUNT(*)
    FROM crm_v3_expert_annotations
    WHERE is_current = TRUE
    GROUP BY 1, 2, 3, 4, 5
""")
for r in cur.fetchall():
    print(r)

print("\n=== OTHER ANNOTATION TABLES IN CRM DB ===")
cur.execute("""
    SELECT table_name 
    FROM information_schema.tables 
    WHERE table_schema='public' AND (table_name LIKE '%annotation%' OR table_name LIKE '%crm%')
    ORDER BY table_name
""")
for r in cur.fetchall():
    print(r[0])

conn.close()
PYEOF
