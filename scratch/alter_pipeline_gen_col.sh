#!/bin/bash
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import psycopg2
conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='document_intelligence',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
conn.autocommit = True
cur=conn.cursor()

# Alter pipeline_generation to VARCHAR(40) to accommodate S13_V3_EXHAUSTIVE_CONTEXT (24 chars)
cur.execute("ALTER TABLE document_processing_queue ALTER COLUMN pipeline_generation TYPE VARCHAR(40)")
print("ALTER TABLE document_processing_queue ALTER COLUMN pipeline_generation TYPE VARCHAR(40) - OK")

# Also check candidate_level (S13_V3_EXHAUSTIVE_CONTEXT would be too long too if used there)
# but candidate_level is only set to DEEP_RESEARCH (12 chars) so VARCHAR(20) is fine

# Verify
cur.execute("SELECT character_maximum_length FROM information_schema.columns WHERE table_name='document_processing_queue' AND column_name='pipeline_generation'")
row = cur.fetchone()
print(f"New pipeline_generation max_length: {row[0]}")
PYEOF
