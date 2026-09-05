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

conn = psycopg2.connect(host=cfg.host, port=cfg.port, dbname="postgres", user=cfg.user, password=cfg.password)
cur = conn.cursor()
cur.execute("SELECT datname FROM pg_database WHERE datistemplate = false;")
dbs = [r[0] for r in cur.fetchall()]
print("DATABASES ON 10.8.0.7:5432:", dbs)

conn.close()

PYEOF
