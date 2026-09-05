#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== PHASE 6D: VERIFY JOIN AND COUNT ==="
PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python -c "
import os, sys
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')
import psycopg2
conn = psycopg2.connect(
    host=os.environ.get('CRM_DB_HOST', '127.0.0.1'),
    port=int(os.environ.get('CRM_DB_PORT', 5432)),
    dbname=os.environ.get('CRM_DB_DATABASE', 'crm'),
    user=os.environ.get('CRM_DB_USER', 'crm_app'),
    password=os.environ.get('CRM_DB_PASSWORD', ''),
)
conn.autocommit = True
cur = conn.cursor()

# Join works?
cur.execute('''
    SELECT sc.subcategory_code, sc.subcategory_name, c.category_code
    FROM crm_product_subcategories sc
    JOIN crm_product_categories c ON c.id = sc.category_id
    ORDER BY c.category_code, sc.subcategory_name
    LIMIT 10
''')
print('=== BATCH JOIN SAMPLE ===')
for r in cur.fetchall():
    print(f'  code={r[0]} name={r[1]} category={r[2]}')

cur.execute('SELECT COUNT(*) FROM crm_product_subcategories')
print(f'TOTAL_SUBCATEGORIES={cur.fetchone()[0]}')

cur.execute('SELECT COUNT(DISTINCT category_id) FROM crm_product_subcategories')
print(f'DISTINCT_CATEGORIES={cur.fetchone()[0]}')

# Verify crm_db.execute_query interface
print('=== CHECK crm_db interface ===')
try:
    from src.bootstrap import connect_databases
    print('connect_databases importable')
except Exception as e:
    print(f'connect_databases: {e}')

conn.close()
print('JOIN_QUERY_PATTERN=WORKS')
" 2>&1

echo "PHASE_6D=DONE"
