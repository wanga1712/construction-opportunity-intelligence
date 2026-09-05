#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

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

print("=== COLUMNS OF crm_v3_expert_annotations ===")
cur.execute("""
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_name='crm_v3_expert_annotations' 
    ORDER BY ordinal_position
""")
for r in cur.fetchall():
    print(f"  {r[0]} ({r[1]})")

print("\n=== TOTAL COUNT IN crm_v3_expert_annotations ===")
cur.execute("SELECT COUNT(*) FROM crm_v3_expert_annotations")
print("Total rows:", cur.fetchone()[0])

print("\n=== COUNT WHERE is_current = TRUE ===")
cur.execute("SELECT COUNT(*) FROM crm_v3_expert_annotations WHERE is_current = TRUE")
print("Total is_current = True:", cur.fetchone()[0])

print("\n=== SAMPLE ROWS (is_current = TRUE) ===")
cur.execute("SELECT * FROM crm_v3_expert_annotations WHERE is_current = TRUE LIMIT 10")
colnames = [desc[0] for desc in cur.description]
print("Columns:", colnames)
for row in cur.fetchall():
    print(dict(zip(colnames, row)))

print("\n=== DISTRIBUTION OF expert_category_scope (is_current = TRUE) ===")
cur.execute("""
    SELECT expert_category_scope, COUNT(*) 
    FROM crm_v3_expert_annotations 
    WHERE is_current = TRUE 
    GROUP BY expert_category_scope
""")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]}")

print("\n=== DISTRIBUTION OF expert_commercial_entry (is_current = TRUE) ===")
cur.execute("""
    SELECT expert_commercial_entry, COUNT(*) 
    FROM crm_v3_expert_annotations 
    WHERE is_current = TRUE 
    GROUP BY expert_commercial_entry
""")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]}")

print("\n=== DISTRIBUTION OF medal (is_current = TRUE) ===")
if "expert_medal_stage" in colnames:
    col = "expert_medal_stage"
elif "medal" in colnames:
    col = "medal"
else:
    col = None

if col:
    cur.execute(f"""
        SELECT {col}, COUNT(*) 
        FROM crm_v3_expert_annotations 
        WHERE is_current = TRUE 
        GROUP BY {col}
    """)
    for r in cur.fetchall():
        print(f"  {r[0]}: {r[1]}")

conn.close()
PYEOF
