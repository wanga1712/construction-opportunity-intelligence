#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== PHASE 8/12/14: REAL UI ACCEPTANCE ==="

echo "--- HTTP timing (initial page load) ---"
T_START=$(date +%s%N)
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8504/ 2>/dev/null)
T_END=$(date +%s%N)
T_HEADER_MS=$(( (T_END - T_START) / 1000000 ))
echo "T_HEADER_MS=$T_HEADER_MS"
echo "HTTP_CODE=$HTTP_CODE"

echo "--- AppTest: real torgi route ---"
PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import time, sys, os
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')

# ── Measure torgi route via Streamlit AppTest ──
try:
    from streamlit.testing.v1 import AppTest
    t0 = time.time()
    at = AppTest.from_file("app.py", default_timeout=30)
    at.run(timeout=30)
    t_total = (time.time() - t0) * 1000
    print(f"T_TOTAL_INITIAL_RENDER_MS={int(t_total)}")

    # Check for exceptions
    if at.exception:
        print(f"APPTEST_EXCEPTION={at.exception}")
    else:
        print("APPTEST_EXCEPTION=NONE")

    # Check markdown headers for torgi counts
    md_texts = [m.value for m in at.markdown]
    for txt in md_texts:
        if 'торги' in txt.lower() or 'торг' in txt.lower():
            print(f"TORGI_HEADER={txt}")

    # Check for tabs
    tab_labels = []
    for tab in getattr(at, 'tabs', []):
        tab_labels.append(str(tab))
    if tab_labels:
        print(f"TABS_FOUND={tab_labels}")

    # Check pills (review filter)
    pills = getattr(at, 'pills', [])
    for p in pills:
        print(f"PILLS={p.label}: {p.value}")

    print(f"MARKDOWN_COUNT={len(at.markdown)}")
    print(f"BUTTON_COUNT={len(at.button)}")

except Exception as e:
    print(f"APPTEST_ERROR={repr(e)}")
    import traceback
    traceback.print_exc()

PYEOF

echo "--- DB counts for UI parity ---"
PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import os, sys, time
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')
import psycopg2

conn = psycopg2.connect(
    host=os.environ.get('CRM_DB_HOST','127.0.0.1'),
    port=int(os.environ.get('CRM_DB_PORT',5432)),
    dbname=os.environ.get('CRM_DB_DATABASE','crm'),
    user=os.environ.get('CRM_DB_USER','crm_app'),
    password=os.environ.get('CRM_DB_PASSWORD',''))
conn.autocommit=True
cur=conn.cursor()

# Match _stage_workset_ids torgi predicate:
# cp.crm_stage='torgi' AND cp.award_status='submission_open'
# AND cp.end_date >= CURRENT_DATE + INTERVAL '2 days'
cur.execute("""
    SELECT
        COUNT(*) AS total,
        COUNT(*) FILTER (WHERE source_table = 'reestr_contract_44_fz') AS fz44,
        COUNT(*) FILTER (WHERE source_table = 'reestr_contract_223_fz') AS fz223,
        COUNT(*) FILTER (WHERE source_table LIKE '%615%') AS pp615
    FROM crm_procurements
    WHERE crm_stage = 'torgi'
      AND award_status = 'submission_open'
      AND end_date >= CURRENT_DATE + INTERVAL '2 days'
""")
row = cur.fetchone()
print(f"DB_ALL={row[0]}")
print(f"DB_44={row[1]}")
print(f"DB_223={row[2]}")
print(f"DB_615={row[3]}")

# Also measure SQL query time for the workset
t0 = time.time()
cur.execute("""
    SELECT DISTINCT cp.id
    FROM crm_procurements cp
    LEFT JOIN crm_category_candidates cc ON cc.procurement_id = cp.id
    WHERE cp.crm_stage='torgi' AND cp.award_status='submission_open'
      AND cp.end_date >= CURRENT_DATE + INTERVAL '2 days'
      AND (TRUE)
    ORDER BY cp.id
""")
ids = [r[0] for r in cur.fetchall()]
t_sql = (time.time() - t0) * 1000
print(f"WORKSET_IDS_COUNT={len(ids)}")
print(f"WORKSET_SQL_MS={int(t_sql)}")

# Measure annotation count query
from src.services.annotation_state_service import count_annotation_states_sql
from src.services.db_bootstrap import connect_databases
_, _, crm_db, _ = connect_databases()

t0 = time.time()
counts = count_annotation_states_sql(ids, crm_db)
t_counts = (time.time() - t0) * 1000
print(f"SQL_COUNTS_MS={int(t_counts)}")
print(f"SQL_COUNTS={counts}")

# Measure page-only annotation load
from src.services.annotation_state_service import load_current_annotation_states
page_ids = ids[:25]
t0 = time.time()
states = load_current_annotation_states(page_ids, crm_db)
t_page = (time.time() - t0) * 1000
print(f"PAGE_ANNOTATION_LOAD_MS={int(t_page)}")
print(f"PAGE_ANNOTATION_COUNT={len(states)}")

conn.close()
PYEOF

echo "PHASE_8_12_14=DONE"
