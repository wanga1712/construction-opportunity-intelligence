#!/bin/bash
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import psycopg2
conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='document_intelligence',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
cur=conn.cursor()

print("=== Altering pipeline_generation columns to VARCHAR(40) ===")
try:
    cur.execute("ALTER TABLE document_files ALTER COLUMN pipeline_generation TYPE VARCHAR(40)")
    print("  document_files altered successfully.")
except Exception as e:
    print("  Error altering document_files:", e)
conn.commit()

try:
    cur.execute("ALTER TABLE document_processing_results ALTER COLUMN pipeline_generation TYPE VARCHAR(40)")
    print("  document_processing_results altered successfully.")
except Exception as e:
    print("  Error altering document_processing_results:", e)
conn.commit()

PYEOF
