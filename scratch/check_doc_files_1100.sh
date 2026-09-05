#!/bin/bash
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import psycopg2
conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='document_intelligence',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
cur=conn.cursor()

print("=== document_files newer rows (> 1100) ===")
cur.execute("""
    SELECT id, queue_id, procurement_id, file_name, download_status, pipeline_generation 
    FROM document_files 
    WHERE id >= 1100 
    ORDER BY id
    LIMIT 15
""")
for r in cur.fetchall():
    print(f"  ID={r[0]}, QID={r[1]}, PID={r[2]}, Name={r[3]}, Status={r[4]}, Gen={r[5]}")

PYEOF
