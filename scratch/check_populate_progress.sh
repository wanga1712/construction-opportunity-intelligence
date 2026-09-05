#!/bin/bash
echo "=== Populate log (last 20 lines) ==="
tail -20 /tmp/populate_actual2.log

echo ""
echo "=== document_processing_queue current count ==="
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import psycopg2
conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='document_intelligence',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
cur=conn.cursor()
cur.execute("SELECT status, COUNT(*) FROM document_processing_queue GROUP BY status ORDER BY status")
rows = cur.fetchall()
total = 0
for row in rows:
    print(f"  {row[0]}: {row[1]}")
    total += row[1]
print(f"  TOTAL: {total}")
PYEOF

echo ""
echo "=== Populate process still running? ==="
ps aux | grep populate_actual | grep -v grep | head -3
