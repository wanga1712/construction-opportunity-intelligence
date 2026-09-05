#!/bin/bash
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import psycopg2
conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='document_intelligence',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
cur=conn.cursor()
cur.execute("""
    SELECT conname, pg_get_constraintdef(c.oid)
    FROM pg_constraint c
    JOIN pg_class t ON c.conrelid = t.oid
    WHERE t.relname = 'document_files'
""")
for row in cur.fetchall():
    print(f"{row[0]}: {row[1]}")
PYEOF
