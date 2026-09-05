#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== PHASE 6: FIX STAGED ANNOTATION IMPORT ERROR ==="

echo "--- Search annotation_card.py for load_subcategories_for_categories ---"
grep -n 'load_subcategories_for_categories' src/ui/components/analytics_v2/annotation_card.py 2>/dev/null || echo "NOT_FOUND_IN_ANNOTATION_CARD"

echo "--- Search expert_annotation_service.py for load_subcategories ---"
grep -n 'load_subcategor' src/services/expert_annotation_service.py 2>/dev/null || echo "NOT_FOUND_IN_EXPERT_SERVICE"

echo "--- Check what subcategory functions exist in expert_annotation_service ---"
grep -n 'def ' src/services/expert_annotation_service.py 2>/dev/null | head -30

echo "--- Check annotation_card imports ---"
grep -n 'from src.services.expert_annotation_service import' src/ui/components/analytics_v2/annotation_card.py 2>/dev/null || echo "NO_IMPORT_FOUND"

echo "--- DB schema: check crm_product_subcategories / crm_product_categories ---"
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

# Check subcategories table
cur.execute(\"\"\"
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_name = 'crm_product_subcategories'
    ORDER BY ordinal_position
\"\"\")
print('=== crm_product_subcategories ===')
for r in cur.fetchall():
    print(f'  {r[0]} ({r[1]})')

# Check categories table
cur.execute(\"\"\"
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_name = 'crm_product_categories'
    ORDER BY ordinal_position
\"\"\")
print('=== crm_product_categories ===')
for r in cur.fetchall():
    print(f'  {r[0]} ({r[1]})')

# Sample join
cur.execute(\"\"\"
    SELECT sc.id, sc.name, sc.category_id, c.code, c.name
    FROM crm_product_subcategories sc
    JOIN crm_product_categories c ON c.id = sc.category_id
    LIMIT 5
\"\"\")
print('=== sample join ===')
for r in cur.fetchall():
    print(f'  subcat_id={r[0]} subcat_name={r[1]} cat_id={r[2]} cat_code={r[3]} cat_name={r[4]}')

conn.close()
" 2>&1

echo "PHASE_6_DISCOVERY=DONE"
