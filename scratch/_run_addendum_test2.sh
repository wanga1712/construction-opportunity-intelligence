#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

ACCEPTANCE_START=$(date -Iseconds)

cat > /tmp/_acceptance_addendum2.py << 'PYEOF'
# -*- coding: utf-8 -*-
import time, sys, os, json
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')
from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')
from streamlit.testing.v1 import AppTest

R = {}

print("=== STARTING ADDENDUM ACCEPTANCE TEST ===")
t0 = time.time()
at = AppTest.from_file("app.py", default_timeout=60)
at.run(timeout=60)
print(f"INITIAL_LOAD_MS={int((time.time()-t0)*1000)}")

# ── Navigate to Торги (index 2) ──
stage_radio = at.radio(key="analytics_v2_active_stage")
opts = list(stage_radio.options)
stage_radio.set_value(opts[2])  # Идут торги
t0 = time.time()
at.run(timeout=60)
R["T_HEADER_MS"] = int((time.time()-t0)*1000)

# Check pills widget
pills_widget = None
print(f"ALL PILLS COUNT: {len(at.pills)}")
for i, p in enumerate(at.pills):
    print(f"  PILLS[{i}]: key={p.key} label={repr(p.label)} options_count={len(p.options)}")
    if p.options:
        pills_widget = p
        break

pill_options = list(pills_widget.options) if pills_widget else []
print(f"SELECTED_PILLS_LABEL={repr(pills_widget.label if pills_widget else None)}")
print(f"PILL_OPTIONS_COUNT={len(pill_options)}")

broken_question_mark_count = 0
broken_text_visible = False

parsed_ui_counts = {}
for opt in pill_options:
    opt_str = str(opt)
    print(f"  OPTION: {repr(opt_str)}")
    if "?" in opt_str or "\ufffd" in opt_str:
        broken_question_mark_count += 1
        broken_text_visible = True
    
    # Parse label and count e.g. "Все · 5152" or "Не проверено · 5150"
    if "·" in opt_str:
        parts = opt_str.split("·")
        lbl = parts[0].strip()
        cnt = int(parts[1].strip())
        parsed_ui_counts[lbl] = cnt

R["BROKEN_QUESTION_MARK_LABELS"] = broken_question_mark_count
R["BROKEN_TEXT_VISIBLE"] = "YES" if broken_text_visible else "NO"
R["REVIEW_FILTER_LABELS_READABLE"] = "YES" if (broken_question_mark_count == 0 and len(pill_options) > 0) else "NO"

print(f"BROKEN_QUESTION_MARK_LABELS={R['BROKEN_QUESTION_MARK_LABELS']}")
print(f"REVIEW_FILTER_LABELS_READABLE={R['REVIEW_FILTER_LABELS_READABLE']}")
print(f"PARSED_UI_COUNTS={json.dumps(parsed_ui_counts, ensure_ascii=False)}")

# Map parsed counts to UI keys
R["UI_WORKSET_TOTAL"] = parsed_ui_counts.get("Все")
R["UI_UNREVIEWED"] = parsed_ui_counts.get("Не проверено")
R["UI_REVIEWED"] = parsed_ui_counts.get("Проверено")
R["UI_IN_CATEGORY"] = parsed_ui_counts.get("В категории")
R["UI_OUT_OF_CATEGORY"] = parsed_ui_counts.get("Вне товарных категорий")
R["UI_COMMERCIAL"] = parsed_ui_counts.get("Коммерчески подходит")
R["UI_NON_COMMERCIAL"] = parsed_ui_counts.get("Коммерчески не подходит")
R["UI_UNCERTAIN"] = parsed_ui_counts.get("Не уверен")
R["UI_LEGACY_NOT_INTERESTING"] = parsed_ui_counts.get("Старые «Неинтересные»")

# ── Test Filter Behavior (clicking each pill option) ──
print("\n=== TESTING FILTER BEHAVIOR ===")
filter_behavior_pass = True
for opt in pill_options:
    opt_str = str(opt)
    pills_widget.set_value(opt)
    t0 = time.time()
    at.run(timeout=60)
    t_filter = int((time.time()-t0)*1000)
    
    page_caption = None
    for c in at.caption:
        if "показано" in str(c.value).lower() or "из" in str(c.value).lower():
            page_caption = str(c.value)
            break
            
    print(f"Filter '{opt_str}': render_ms={t_filter}, caption={repr(page_caption)}, exc={len(at.exception)}")
    if at.exception:
        filter_behavior_pass = False
        for exc in at.exception:
            print(f"  EXC={exc.value[:200]}")

R["REVIEW_FILTER_BEHAVIOR"] = "PASS" if filter_behavior_pass else "FAIL"

# Check invariant REVIEWED + UNREVIEWED = TOTAL
if R["UI_REVIEWED"] is not None and R["UI_UNREVIEWED"] is not None and R["UI_WORKSET_TOTAL"] is not None:
    R["REVIEWED_PLUS_UNREVIEWED_EQUALS_TOTAL"] = "YES" if (R["UI_REVIEWED"] + R["UI_UNREVIEWED"] == R["UI_WORKSET_TOTAL"]) else "NO"
else:
    R["REVIEWED_PLUS_UNREVIEWED_EQUALS_TOTAL"] = "UNKNOWN"

# Reset filter back to ALL
if pill_options:
    pills_widget.set_value(pill_options[0])
    at.run(timeout=60)

print("\n=== ACCEPTANCE TEST FINAL RESULTS ===")
for k in sorted(R):
    print(f"{k}={R[k]}")

PYEOF

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python /tmp/_acceptance_addendum2.py 2>&1

echo "=== PHASE 13 LOG CHECK ==="
journalctl -u crm-streamlit.service --since "$ACCEPTANCE_START" --no-pager 2>&1 | grep -ic 'traceback\|importerror' | xargs -I{} echo "STREAMLIT_TRACEBACKS={}"

echo "=== AUTONOMOUS WORKER CHECK ==="
systemctl is-active crm-v3-autonomous-worker.service && echo "WORKER_ACTIVE=YES" || echo "WORKER_ACTIVE=NO"
pgrep -c -f 'autonomous_worker' | xargs -I{} echo "WORKER_COUNT={}"

echo "=== GIT HYGIENE CHECK ==="
cd /opt/CRM_Streamlit_rescue
echo "GIT_DIRTY_COUNT=$(git status --porcelain | wc -l)"
echo "COMMITTED_PYC_COUNT=$(git ls-files | grep -cE '(__pycache__/|\.pyc$)' || echo 0)"
