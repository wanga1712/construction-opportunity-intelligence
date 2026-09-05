#!/bin/bash
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import psycopg2
conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='document_intelligence',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
cur=conn.cursor()
cur.execute("""
    SELECT indexname, indexdef
    FROM pg_indexes
    WHERE tablename = 'document_processing_results'
""")
for row in cur.fetchall():
    print(f"{row[0]}: {row[1]}")
PYEOF
