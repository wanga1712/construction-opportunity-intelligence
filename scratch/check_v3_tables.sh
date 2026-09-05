#!/bin/bash
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import psycopg2
conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='crm',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
cur=conn.cursor()

print("=== CRM V3 Learning Loop Tables ===")
for tbl in ['crm_v3_pre_research_snapshots', 'crm_v3_research_truths', 'crm_v3_evaluation_results', 'crm_v3_learning_examples']:
    cur.execute(f"SELECT COUNT(*) FROM {tbl}")
    print(f"  {tbl}: {cur.fetchone()[0]}")
PYEOF
