#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== PHASE 6C: FIX N+1 SUBCATEGORY BATCH ==="

# Check if category_code column exists on crm_product_subcategories
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
cur = conn.cursor()

# Does subcategories have category_code?
cur.execute(\"\"\"
    SELECT column_name FROM information_schema.columns
    WHERE table_name = 'crm_product_subcategories'
    AND column_name = 'category_code'
\"\"\")
has_code = cur.fetchone()
print(f'SUBCATEGORIES_HAS_CATEGORY_CODE={\"YES\" if has_code else \"NO\"}')

# Try the existing query pattern
try:
    cur.execute(\"\"\"
        SELECT subcategory_code, subcategory_name
        FROM crm_product_subcategories
        WHERE category_code = 'TEST_NONEXISTENT'
    \"\"\")
    print('EXISTING_QUERY_PATTERN=WORKS (category_code column exists)')
except Exception as e:
    print(f'EXISTING_QUERY_PATTERN=FAILS ({e})')

# Try the join pattern
try:
    cur.execute(\"\"\"
        SELECT sc.subcategory_code, sc.subcategory_name, c.category_code
        FROM crm_product_subcategories sc
        JOIN crm_product_categories c ON c.id = sc.category_id
        WHERE c.category_code IN ('TEST_NONEXISTENT')
        ORDER BY sc.subcategory_name
    \"\"\")
    print('JOIN_QUERY_PATTERN=WORKS')
except Exception as e:
    print(f'JOIN_QUERY_PATTERN=FAILS ({e})')

# Count actual data
cur.execute('SELECT COUNT(*) FROM crm_product_subcategories')
total = cur.fetchone()[0]
print(f'TOTAL_SUBCATEGORIES={total}')

cur.execute('SELECT COUNT(DISTINCT category_id) FROM crm_product_subcategories')
cats = cur.fetchone()[0]
print(f'DISTINCT_CATEGORIES_WITH_SUBCATEGORIES={cats}')

conn.close()
" 2>&1

echo "PHASE_6C=DONE"
