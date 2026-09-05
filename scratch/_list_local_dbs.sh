#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os, psycopg2
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

# Try connecting to local postgres using socket or local postgres user
try:
    conn = psycopg2.connect(dbname="postgres", user="sergey")
except Exception as e1:
    try:
        conn = psycopg2.connect(dbname="postgres", user="postgres")
    except Exception as e2:
        print("Error 1:", e1)
        print("Error 2:", e2)
        sys.exit(1)

cur = conn.cursor()
cur.execute("SELECT datname FROM pg_database WHERE datistemplate = false;")
dbs = [r[0] for r in cur.fetchall()]
print("LOCAL DATABASES ON 127.0.0.1:", dbs)

found = None
for db in dbs:
    try:
        c = psycopg2.connect(dbname=db)
        cu = c.cursor()
        cu.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE '%queue%' OR table_name LIKE '%document%'")
        rows = cu.fetchall()
        if rows:
            print(f"Local DB '{db}' has tables: {[r[0] for r in rows]}")
            if any('document_processing_queue' in r[0] for r in rows):
                found = db
        c.close()
    except Exception as e:
        pass

print(f"\nLOCAL DB FOR document_processing_queue: {found}")

PYEOF
