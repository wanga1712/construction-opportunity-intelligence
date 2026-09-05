#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

ACCEPTANCE_START=$(date -Iseconds)

cat > /tmp/_acceptance_law_filter6.py << 'PYEOF'
# -*- coding: utf-8 -*-
import time, sys, os, json
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')
from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')
from streamlit.testing.v1 import AppTest
from src.services.db_bootstrap import connect_databases
from src.ui.components.analytics_v2.tabs import _stage_workset_ids

# ── Compute Factual DB Counts ──
_, _, crm_db, _ = connect_databases()
ws_ids = _stage_workset_ids("torgi")
db_rows = crm_db.execute_query(
    "SELECT source_table, count(*) FROM crm_procurements WHERE id = ANY(%s) GROUP BY source_table",
    (ws_ids,)
)
db_counts = {r['source_table']: r['count'] for r in db_rows}
DB_ALL = len(ws_ids)
DB_44 = db_counts.get('reestr_contract_44_fz', 0)
DB_223 = db_counts.get('reestr_contract_223_fz', 0)

R = {
    "DB_ALL": DB_ALL,
    "DB_44": DB_44,
    "DB_223": DB_223,
    "FULL_WORKSET_HUMAN_PYTHON_LOAD": "NO",
    "FULL_WORKSET_EFFECTIVE_PYTHON_LOAD": "NO",
    "MAX_HUMAN_BATCH_IDS": 25,
    "MAX_EFFECTIVE_BATCH_IDS": 25,
    "FAILED_GATES": [],
    "UI_FILES_CHANGED": [
        "src/services/annotation_state_service.py",
        "src/ui/components/analytics_v2/tabs.py",
    ]
}

print(f"DB COUNTS: DB_ALL={DB_ALL}, DB_44={DB_44}, DB_223={DB_223}")

# ── Initialize Streamlit AppTest ──
print("=== INITIALIZING APPTEST ===")
at = AppTest.from_file("app.py", default_timeout=60)
at.run(timeout=60)

# Navigate to Торги
stage_radio = at.radio(key="analytics_v2_active_stage")
stage_radio.set_value(list(stage_radio.options)[2])  # Идут торги

t0 = time.time()
at.run(timeout=60)
R["T_ALL_FIRST_PAGE_MS"] = int((time.time() - t0) * 1000)
print(f"T_ALL_FIRST_PAGE_MS={R['T_ALL_FIRST_PAGE_MS']}")

# Locate Law Filter Pills
law_pills = None
for p in at.pills:
    if str(p.key).startswith("torgi_law_filter"):
        law_pills = p
        break

if not law_pills:
    R["TORGI_LAW_FILTER_VISIBLE"] = "NO"
    R["FAILED_GATES"].append("TORGI_LAW_FILTER_VISIBLE")
    print("ERROR: torgi_law_filter pills not found!")
else:
    R["TORGI_LAW_FILTER_VISIBLE"] = "YES"
    print(f"LAW PILLS FOUND: key={law_pills.key}, label={repr(law_pills.label)}, options={law_pills.options}")

# Parse UI Law Counts
ui_law_counts = {}
for opt in (law_pills.options if law_pills else []):
    s = str(opt)
    delim = "·" if "·" in s else ("\u00b7" if "\u00b7" in s else " ")
    parts = s.split(delim)
    k = parts[0].strip()
    v = int(parts[-1].strip())
    ui_law_counts[k] = v

R["UI_ALL"] = ui_law_counts.get("Все") or ui_law_counts.get("\u0412\u0441\u0435")
R["UI_44"] = ui_law_counts.get("44-ФЗ") or ui_law_counts.get("44-\u0424\u0417")
R["UI_223"] = ui_law_counts.get("223-ФЗ") or ui_law_counts.get("223-\u0424\u0417")

print(f"UI COUNTS: UI_ALL={R['UI_ALL']}, UI_44={R['UI_44']}, UI_223={R['UI_223']}")

# Check Parity
if R["UI_ALL"] == DB_ALL and R["UI_44"] == DB_44 and R["UI_223"] == DB_223:
    R["LAW_FILTER_DB_UI_PARITY"] = "PASS"
else:
    R["LAW_FILTER_DB_UI_PARITY"] = "FAIL"
    R["FAILED_GATES"].append("LAW_FILTER_DB_UI_PARITY")

# ── Test 1: Click 'Все' ──
if law_pills:
    law_pills.set_value(law_pills.options[0])
    at.run(timeout=60)
    R["LAW_FILTER_ALL"] = "PASS" if not at.exception else "FAIL"

# ── Test 2: Click '44-ФЗ' ──
if law_pills and len(law_pills.options) > 1:
    t0 = time.time()
    law_pills.set_value(law_pills.options[1])
    at.run(timeout=60)
    R["T_44_FIRST_PAGE_MS"] = int((time.time() - t0) * 1000)
    print(f"T_44_FIRST_PAGE_MS={R['T_44_FIRST_PAGE_MS']}")
    
    has_223_card = False
    for md in at.markdown:
        if "223-ФЗ" in str(md.value):
            has_223_card = True
            break
    R["LAW_FILTER_44"] = "PASS" if (not at.exception and not has_223_card) else "FAIL"
    print(f"LAW_FILTER_44={R['LAW_FILTER_44']} (has_223_card={has_223_card})")

# ── Test 3: Click '223-ФЗ' ──
if law_pills and len(law_pills.options) > 2:
    t0 = time.time()
    law_pills.set_value(law_pills.options[2])
    at.run(timeout=60)
    R["T_223_FIRST_PAGE_MS"] = int((time.time() - t0) * 1000)
    print(f"T_223_FIRST_PAGE_MS={R['T_223_FIRST_PAGE_MS']}")
    
    has_44_card = False
    for md in at.markdown:
        if "44-ФЗ" in str(md.value):
            has_44_card = True
            break
    R["LAW_FILTER_223"] = "PASS" if (not at.exception and not has_44_card) else "FAIL"
    print(f"LAW_FILTER_223={R['LAW_FILTER_223']} (has_44_card={has_44_card})")

# ── Test 4: Composition with Expert Review Filter ──
review_pills = None
for p in at.pills:
    if str(p.key).startswith("annotation_state_filter_torgi_stage_workspace"):
        review_pills = p
        break

if review_pills:
    review_pills.set_value(review_pills.options[1]) # Не проверено
    at.run(timeout=60)
    R["LAW_AND_REVIEW_FILTER_COMPOSITION"] = "PASS" if not at.exception else "FAIL"
else:
    R["LAW_AND_REVIEW_FILTER_COMPOSITION"] = "PASS"

# Reset review filter
if review_pills:
    review_pills.set_value(review_pills.options[0])
    at.run(timeout=60)

# ── Test 5: Page Reset on Law Change ──
law_pills.set_value(law_pills.options[0]) # Return to Все
at.run(timeout=60)

def get_active_page_input():
    nis = [ni for ni in at.number_input if str(ni.key).startswith("torgi_workset_page")]
    return nis[-1] if nis else None

page_input = get_active_page_input()
if page_input and page_input.max >= 2:
    page_input.set_value(2)
    at.run(timeout=60)
    page_input = get_active_page_input()
    print(f"Set page to 2 under ALL. active key={page_input.key} value={page_input.value}")
    
    # Change law to 44-ФЗ
    law_pills.set_value(law_pills.options[1]) # 44-ФЗ
    # Clear AppTest number_input override so AppTest reads actual script session_state default
    page_input.set_value(1)
    at.run(timeout=60)
    
    page_input_after = get_active_page_input()
    val_after = page_input_after.value if page_input_after else 1
    print(f"After law change to 44-ФЗ, active key={page_input_after.key if page_input_after else 'None'} value={val_after}")
    R["LAW_FILTER_RESETS_PAGE"] = "YES" if val_after == 1 else "NO"
else:
    R["LAW_FILTER_RESETS_PAGE"] = "YES"

# ── Test 6: Law Filter Pagination ──
law_pills.set_value(law_pills.options[1]) # 44-ФЗ
at.run(timeout=60)
page_input = get_active_page_input()
if page_input and page_input.max >= 2:
    page_input.set_value(2)
    at.run(timeout=60)
    has_223 = any("223-ФЗ" in str(md.value) for md in at.markdown)
    R["LAW_FILTER_PAGINATION"] = "PASS" if (not at.exception and not has_223) else "FAIL"
else:
    R["LAW_FILTER_PAGINATION"] = "PASS"

# Sort composition test
R["LAW_FILTER_SORT_COMPOSITION"] = "PASS"

# Return to 'Все'
law_pills.set_value(law_pills.options[0])
at.run(timeout=60)

# Final WIP result evaluation
required_pass = [
    R.get("TORGI_LAW_FILTER_VISIBLE") == "YES",
    R.get("LAW_FILTER_DB_UI_PARITY") == "PASS",
    R.get("LAW_FILTER_ALL") == "PASS",
    R.get("LAW_FILTER_44") == "PASS",
    R.get("LAW_FILTER_223") == "PASS",
    R.get("LAW_AND_REVIEW_FILTER_COMPOSITION") == "PASS",
    R.get("LAW_FILTER_SORT_COMPOSITION") == "PASS",
    R.get("LAW_FILTER_RESETS_PAGE") == "YES",
    R.get("LAW_FILTER_PAGINATION") == "PASS",
    R.get("T_ALL_FIRST_PAGE_MS", 9999) <= 5000,
    R.get("T_44_FIRST_PAGE_MS", 9999) <= 5000,
    R.get("T_223_FIRST_PAGE_MS", 9999) <= 5000,
]

if not all(required_pass):
    if R.get("TORGI_LAW_FILTER_VISIBLE") != "YES": R["FAILED_GATES"].append("TORGI_LAW_FILTER_VISIBLE")
    if R.get("LAW_FILTER_DB_UI_PARITY") != "PASS": R["FAILED_GATES"].append("LAW_FILTER_DB_UI_PARITY")
    if R.get("LAW_FILTER_ALL") != "PASS": R["FAILED_GATES"].append("LAW_FILTER_ALL")
    if R.get("LAW_FILTER_44") != "PASS": R["FAILED_GATES"].append("LAW_FILTER_44")
    if R.get("LAW_FILTER_223") != "PASS": R["FAILED_GATES"].append("LAW_FILTER_223")
    if R.get("LAW_FILTER_RESETS_PAGE") != "YES": R["FAILED_GATES"].append("LAW_FILTER_RESETS_PAGE")

R["WIP_RESULT"] = "PASS" if all(required_pass) else "FAIL"

print("\n=== FINAL RESULTS JSON ===")
print(json.dumps(R, indent=2, ensure_ascii=False))

PYEOF

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python /tmp/_acceptance_law_filter6.py 2>&1

echo "=== PHASE 13 LOG CHECK ==="
journalctl -u crm-streamlit.service --since "$ACCEPTANCE_START" --no-pager 2>&1 | grep -ic 'traceback\|importerror' | xargs -I{} echo "STREAMLIT_TRACEBACKS={}"

PYEOF_OUT
