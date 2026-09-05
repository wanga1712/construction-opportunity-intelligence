#!/bin/bash
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import psycopg2
# doc_worker is the DBA for document_intelligence
conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='document_intelligence',user='doc_worker',password='F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT')
conn.autocommit = True
cur=conn.cursor()

cur.execute("ALTER TABLE document_processing_queue ALTER COLUMN pipeline_generation TYPE VARCHAR(40)")
print("ALTER pipeline_generation VARCHAR(40) - OK")

# Also grant crm_app write access if not already
try:
    cur.execute("GRANT INSERT, UPDATE, DELETE ON document_processing_queue TO crm_app")
    print("GRANT INSERT, UPDATE, DELETE ON document_processing_queue TO crm_app - OK")
except Exception as e:
    print(f"GRANT note: {e}")

cur.execute("SELECT character_maximum_length FROM information_schema.columns WHERE table_name='document_processing_queue' AND column_name='pipeline_generation'")
row = cur.fetchone()
print(f"pipeline_generation max_length: {row[0]}")
PYEOF
