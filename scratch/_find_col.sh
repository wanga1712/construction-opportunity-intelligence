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

# Find law-related column
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='crm_procurements' ORDER BY ordinal_position")
for r in cur.fetchall():
    print(r[0])
PYEOF
