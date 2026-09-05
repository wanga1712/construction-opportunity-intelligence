#!/bin/bash
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import psycopg2
conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='crm',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
cur=conn.cursor()
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE 'crm_v3%'")
for row in cur.fetchall():
    print(row[0])
PYEOF
