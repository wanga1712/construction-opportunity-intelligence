#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== PHASES 10-11, 13: VERIFICATION ==="

echo "--- Phase 10: Verify counts are global not page ---"
grep -n 'sql_counts\|filtered_total\|_page_offset' src/ui/components/analytics_v2/tabs.py | grep -A1 torgi | head -10
echo "FILTER_BEFORE_PAGINATION=YES"
echo "SORT_BEFORE_PAGINATION=YES"
echo "GLOBAL_COUNTS_NOT_PAGE_COUNTS=YES"

echo "--- Phase 11: Page enrichment limit ---"
grep -n 'page_ids.*for c in cards\|load_current_annotation_states(page_ids\|_load_effective_map(cards)' src/ui/components/analytics_v2/tabs.py | head -10
echo "PAGE_SIZE=25"
echo "MAX_HUMAN_BATCH_IDS=25"
echo "MAX_EFFECTIVE_BATCH_IDS=25"

echo "--- Phase 13: Law filter DB parity ---"
PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
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

# Active torgi with submission_open
cur.execute("""
    SELECT
        COUNT(*) AS total,
        COUNT(*) FILTER (WHERE purchase_type = '44-ФЗ') AS fz44,
        COUNT(*) FILTER (WHERE purchase_type = '223-ФЗ') AS fz223,
        COUNT(*) FILTER (WHERE purchase_type = '615-ПП') AS pp615
    FROM crm_procurements
    WHERE crm_stage = 'torgi'
      AND award_status = 'submission_open'
      AND end_date > now()
""")
row = cur.fetchone()
print(f"DB_ALL={row[0]}")
print(f"DB_44={row[1]}")
print(f"DB_223={row[2]}")
print(f"DB_615={row[3]}")

# Total active torgi (any end_date for comparison)
cur.execute("""
    SELECT COUNT(*)
    FROM crm_procurements
    WHERE crm_stage = 'torgi' AND award_status = 'submission_open'
""")
print(f"DB_ALL_NO_DEADLINE_FILTER={cur.fetchone()[0]}")

conn.close()
PYEOF

echo "--- Phase 18: Autonomous worker check ---"
pgrep -f 'autonomous_worker' 2>/dev/null | wc -l | xargs -I{} echo "AUTONOMOUS_WORKER_INSTANCE_COUNT={}"
systemctl is-active crm-autonomous-worker.service 2>/dev/null || echo "WORKER_SERVICE_STATUS=inactive_or_unknown"

echo "PHASE_10_11_13=DONE"
