#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os, psycopg2
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
sys.path.insert(0, '/opt/pythonProject89')
os.chdir('/opt/CRM_Streamlit_rescue')

from src.services.db_bootstrap import connect_databases

tender_db, radar_db, crm_db, _ = connect_databases()
cfg = crm_db._config

doc_dsn = {
    "host": cfg.host,
    "port": cfg.port,
    "dbname": "document_intelligence",
    "user": cfg.user,
    "password": cfg.password,
}

conn = psycopg2.connect(**doc_dsn)
cur = conn.cursor()
cur.execute("SELECT count(*) FROM document_processing_queue")
cnt = cur.fetchone()[0]
print(f"DOCUMENT_PROCESSING_QUEUE COUNT = {cnt}")
conn.close()

PYEOF
