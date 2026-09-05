#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os, json
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')

from src.services.commercial_routing_v3.factual_feeder import _get_doc_db_conn

conn = _get_doc_db_conn()
cur = conn.cursor()

# Query content types and file extensions in document_files
cur.execute("""
    SELECT DISTINCT content_type, substring(file_name from '\.([a-zA-Z0-9]+)$') as ext, count(*)
    FROM document_files
    GROUP BY content_type, ext
    ORDER BY count(*) DESC
""")

print("=== DOCUMENT FILES FORMAT DISTRIBUTION ===")
for r in cur.fetchall():
    print(f"  ContentType: {r[0]}, Ext: {r[1]}, Count: {r[2]}")

# Query sample local_path values
cur.execute("SELECT local_path FROM document_files WHERE local_path IS NOT NULL LIMIT 5")
print("\n=== SAMPLE LOCAL PATHS ===")
for r in cur.fetchall():
    print(f"  {r[0]} (exists: {os.path.exists(r[0]) if r[0] else False})")

conn.close()

PYEOF
