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
conn.close()

found_db = None
for db in dbs:
    try:
        c = psycopg2.connect(host=cfg.host, port=cfg.port, dbname=db, user=cfg.user, password=cfg.password)
        cu = c.cursor()
        cu.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE '%document%queue%' OR table_name LIKE '%queue%'")
        rows = cu.fetchall()
        if rows:
            print(f"DB '{db}' has queue tables: {[r[0] for r in rows]}")
            if any('document_processing_queue' in r[0] for r in rows):
                found_db = db
        c.close()
    except Exception:
        pass

print(f"\nFOUND DATABASE FOR document_processing_queue: {found_db}")

PYEOF
