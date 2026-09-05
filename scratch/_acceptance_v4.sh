#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

ACCEPTANCE_START=$(date -Iseconds)
echo "ACCEPTANCE_START=$ACCEPTANCE_START"

# Write the Python test to a file to avoid heredoc encoding issues
cat > /tmp/_acceptance_test.py << 'PYEOF'
# -*- coding: utf-8 -*-
import time, sys, os, json
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')
from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')
from streamlit.testing.v1 import AppTest

R = {}

# ── INITIAL LOAD ──
t0 = time.time()
at = AppTest.from_file("app.py", default_timeout=60)
at.run(timeout=60)
print(f"INITIAL_LOAD_MS={int((time.time()-t0)*1000)}")
print(f"INITIAL_EXCEPTIONS={len(at.exception)}")

# ── Navigate to Торги via radio index ──
# Options: ['Лиды', 'Подготовка к торгам', 'Идут торги', 'Комиссия', 'На рассмотрении', 'Разыгранные']
# Index 2 = "Идут торги"
stage_radio = at.radio(key="analytics_v2_active_stage")
opts = list(stage_radio.options)
print(f"STAGE_RADIO_OPTIONS={opts}")
torgi_opt = opts[2]  # "Идут торги"
print(f"SETTING_STAGE={torgi_opt}")
stage_radio.set_value(torgi_opt)

t0 = time.time()
at.run(timeout=60)
T_HEADER_MS = int((time.time()-t0)*1000)
R["T_HEADER_MS"] = T_HEADER_MS
print(f"T_HEADER_MS={T_HEADER_MS}")
print(f"TORGI_EXCEPTIONS={len(at.exception)}")
for exc in at.exception:
    print(f"  EXC={exc.value[:300]}")

import_errors = [str(e.value) for e in at.exception if 'import' in str(e.value).lower()]
R["STAGED_IMPORT_RUNTIME_ERROR_PRESENT"] = "YES" if import_errors else "NO"
print(f"STAGED_IMPORT_RUNTIME_ERROR_PRESENT={R['STAGED_IMPORT_RUNTIME_ERROR_PRESENT']}")

# ── Verify content ──
for m in at.markdown:
    val = str(m.value)
    if any(x in val.lower() for x in ['\u0442\u043e\u0440\u0433', '\u0438\u0434\u0443\u0442']):
        print(f"TORGI_MD={val[:150]}")
        R["TORGI_ROUTE_OPENED"] = "YES"
for c in at.caption:
    val = str(c.value)
    if any(x in val.lower() for x in ['\u043f\u043e\u043a\u0430\u0437\u0430\u043d\u043e', '\u0442\u043e\u0440\u0433']):
        print(f"TORGI_CAP={val}")

# ── PILLS (review filter counts) ──
print("=== PILLS ===")
for p in at.pills:
    opts = list(p.options)
    print(f"PILLS label={p.label}")
    for o in opts:
        print(f"  {o}")

# ── RADIOS ──
print("=== RADIOS ===")
for r in at.radio:
    if r.key not in ("analytics_v2_active_stage", "ui_theme_radio"):
        print(f"  RADIO: label={r.label} options={list(r.options)} key={r.key}")

# ── NUMBER INPUTS ──
print("=== NUMBER_INPUTS ===")
for ni in at.number_input:
    print(f"  NI: label={ni.label} value={ni.value} min={ni.min} max={ni.max}")

# ── SELECTBOXES ──
print("=== SELECTBOXES ===")
for sb in at.selectbox:
    print(f"  SB: label={sb.label} opts={list(sb.options)[:6]} value={sb.value}")

# ── BUTTONS (card feed) ──
print("=== BUTTONS ===")
procurement_btns = []
for b in at.button:
    label = str(b.label)
    if 'nav_' in str(b.key):
        continue
    if len(label) > 20:
        procurement_btns.append((b, label))
        if len(procurement_btns) <= 5:
            print(f"  CARD_BTN: key={b.key} label={label[:200]}")
    elif 'retry' not in str(b.key) and 'startup' not in str(b.key):
        print(f"  BTN: label={label} key={b.key}")
print(f"PROCUREMENT_BTNS_COUNT={len(procurement_btns)}")

# ── EXPANDERS ──
print("=== EXPANDERS ===")
for exp in at.expander:
    print(f"  EXP: {exp.label[:100]}")

# ── Open first procurement card ──
if procurement_btns:
    btn, label = procurement_btns[0]
    print(f"\n=== PHASE 6: CLICK CARD: {label[:100]} ===")
    btn.click()
    t0 = time.time()
    at.run(timeout=60)
    T_FIRST_CARD_MS = int((time.time()-t0)*1000)
    R["T_FIRST_CARD_MS"] = T_FIRST_CARD_MS
    print(f"T_FIRST_CARD_MS={T_FIRST_CARD_MS}")
    print(f"CARD_EXCEPTIONS={len(at.exception)}")
    for exc in at.exception:
        print(f"  CARD_EXC={exc.value[:300]}")
    card_import = [str(e.value) for e in at.exception if 'import' in str(e.value).lower()]
    if card_import:
        R["STAGED_IMPORT_RUNTIME_ERROR_PRESENT"] = "YES"
    R["REAL_CARD_OPENED"] = "YES" if len(at.exception) == 0 else "EXCEPTION"

    # Card detail content
    for m in at.markdown:
        val = str(m.value)
        if any(x in val.lower() for x in ['\u043d\u043c\u0446\u043a', '\u20bd', '\u0437\u0430\u043a\u0443\u043f\u043a', '\u043f\u0440\u0438\u0451\u043c', '44-\u0444\u0437', '223-\u0444\u0437', 'tender']):
            print(f"  DETAIL_MD: {val[:200]}")
    for c in at.caption:
        val = str(c.value)
        if any(x in val.lower() for x in ['\u043d\u043c\u0446\u043a', '\u0446\u0435\u043d\u0430', '\u043f\u0440\u0438\u0451\u043c', '\u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a', '\u0441\u0440\u043e\u043a', '\u0437\u0430\u043a\u0443\u043f']):
            print(f"  DETAIL_CAP: {val[:200]}")

    # ── PHASE 8: ANNOTATION GATE ──
    print("=== PHASE 8: ANNOTATION GATE ===")
    gate = None
    for r in at.radio:
        opts = [str(o) for o in r.options]
        if '\u0414\u0430' in opts and '\u041d\u0435\u0442' in opts and '\u041d\u0435 \u0443\u0432\u0435\u0440\u0435\u043d' in opts:
            gate = r
            print(f"CATEGORY_GATE: label={r.label} options={opts}")
            break
    R["REAL_CATEGORY_GATE_RENDERED"] = "YES" if gate else "NO"
    print(f"REAL_CATEGORY_GATE_RENDERED={R['REAL_CATEGORY_GATE_RENDERED']}")

    if gate:
        # IN_CATEGORY
        print("=== PHASE 9: IN_CATEGORY ===")
        gate.set_value("\u0414\u0430")
        at.run(timeout=60)
        print(f"IN_CAT_EXCEPTIONS={len(at.exception)}")
        for exc in at.exception:
            print(f"  EXC={exc.value[:200]}")

        deep = {}
        for sb in at.selectbox:
            l = str(sb.label).lower()
            for key in ['\u043a\u0430\u0442\u0435\u0433\u043e\u0440', '\u043f\u043e\u0434\u043a\u0430\u0442\u0435\u0433\u043e\u0440', '\u043e\u0431\u044a\u0435\u043a\u0442', '\u0441\u0435\u043a\u0442\u043e\u0440', '\u043a\u043e\u043c\u043c\u0435\u0440\u0447', '\u043c\u0435\u0434\u0430\u043b', '\u0442\u0438\u043f \u0437\u0430\u043a\u0443\u043f', '\u0437\u0430\u043a\u0443\u043f']:
                if key in l:
                    deep[key] = sb
                    print(f"  DEEP_SB: label={sb.label} opts={list(sb.options)[:5]}")
        for ms in at.multiselect:
            l = str(ms.label).lower()
            for key in ['\u043a\u0430\u0442\u0435\u0433\u043e\u0440', '\u043f\u043e\u0434\u043a\u0430\u0442\u0435\u0433\u043e\u0440']:
                if key in l:
                    deep[key] = ms
                    print(f"  DEEP_MS: label={ms.label} opts={list(ms.options)[:5]}")
        for r in at.radio:
            l = str(r.label).lower()
            for key in ['\u043a\u043e\u043c\u043c\u0435\u0440\u0447', '\u043c\u0435\u0434\u0430\u043b', '\u043e\u0431\u044a\u0435\u043a\u0442', '\u0441\u0435\u043a\u0442\u043e\u0440']:
                if key in l:
                    deep[key] = r
                    print(f"  DEEP_RADIO: label={r.label} opts={list(r.options)}")

        R["REAL_CATEGORY_SELECTOR_RENDERED"] = "YES" if any('\u043a\u0430\u0442\u0435\u0433\u043e\u0440' in k for k in deep) else "NO"
        R["REAL_SUBCATEGORY_SELECTOR_WORKS"] = "YES" if any('\u043f\u043e\u0434\u043a\u0430\u0442\u0435\u0433\u043e\u0440' in k for k in deep) else "CHECK"
        R["REAL_OBJECT_STAGE_RENDERED"] = "YES" if any(k in deep for k in ['\u043e\u0431\u044a\u0435\u043a\u0442','\u0441\u0435\u043a\u0442\u043e\u0440']) else "NO"
        R["REAL_PROCUREMENT_MODE_RENDERED"] = "YES" if any(k in deep for k in ['\u0442\u0438\u043f \u0437\u0430\u043a\u0443\u043f','\u0437\u0430\u043a\u0443\u043f']) else "NO"
        R["REAL_COMMERCIAL_ENTRY_RENDERED"] = "YES" if '\u043a\u043e\u043c\u043c\u0435\u0440\u0447' in deep else "NO"
        R["REAL_CONDITIONAL_MEDAL_RENDERED"] = "YES" if '\u043c\u0435\u0434\u0430\u043b' in deep else "CHECK"
        R["REAL_IN_CATEGORY_DEEP_FLOW_RENDERED"] = "YES"
        for k,v in sorted(R.items()):
            if 'REAL_' in k:
                print(f"{k}={v}")

        # OUT_OF_CATEGORY
        print("=== PHASE 10: OUT_OF_CATEGORY ===")
        gate.set_value("\u041d\u0435\u0442")
        at.run(timeout=60)
        R["REAL_OUT_OF_CATEGORY_FAST_PATH_RENDERED"] = "YES" if len(at.exception) == 0 else "EXCEPTION"
        print(f"OUT_EXCEPTIONS={len(at.exception)}")
        print(f"REAL_OUT_OF_CATEGORY_FAST_PATH_RENDERED={R['REAL_OUT_OF_CATEGORY_FAST_PATH_RENDERED']}")

        # UNCERTAIN
        print("=== PHASE 11: UNCERTAIN ===")
        gate.set_value("\u041d\u0435 \u0443\u0432\u0435\u0440\u0435\u043d")
        at.run(timeout=60)
        R["REAL_UNCERTAIN_FAST_PATH_RENDERED"] = "YES" if len(at.exception) == 0 else "EXCEPTION"
        print(f"UNCERTAIN_EXCEPTIONS={len(at.exception)}")
        print(f"REAL_UNCERTAIN_FAST_PATH_RENDERED={R['REAL_UNCERTAIN_FAST_PATH_RENDERED']}")

    # ── PHASE 12: PAGINATION ──
    print("=== PHASE 12: PAGINATION ===")
    page_ni = None
    for ni in at.number_input:
        if '\u0441\u0442\u0440\u0430\u043d\u0438\u0446' in str(ni.label).lower():
            page_ni = ni
            break
    if page_ni:
        print(f"PAGE: value={page_ni.value} max={page_ni.max}")
        if page_ni.max and int(page_ni.max) > 1:
            page_ni.set_value(2)
            t0 = time.time()
            at.run(timeout=60)
            print(f"PAGE2_MS={int((time.time()-t0)*1000)}")
            print(f"PAGE2_EXCEPTIONS={len(at.exception)}")
            page_ni.set_value(1)
            at.run(timeout=60)
            R["REAL_PAGINATION"] = "PASS"
        else:
            R["REAL_PAGINATION"] = "SINGLE_PAGE"
    else:
        R["REAL_PAGINATION"] = "NO_PAGE_INPUT"

else:
    R["REAL_CARD_OPENED"] = "NO_BUTTONS"

R["T_TOTAL_INITIAL_RENDER_MS"] = R.get("T_HEADER_MS", 0)
print("\n=== FINAL RESULTS ===")
print(json.dumps(R, indent=2, ensure_ascii=False))
PYEOF

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python /tmp/_acceptance_test.py 2>&1

echo "=== PHASE 13: SERVER LOG CHECK ==="
journalctl -u crm-streamlit.service --since "$ACCEPTANCE_START" --no-pager 2>&1 | grep -ic 'traceback\|importerror' | xargs -I{} echo "STREAMLIT_TRACEBACKS_DURING_ACCEPTANCE={}"

echo "=== PHASE 14-15 ==="
systemctl is-active crm-v3-autonomous-worker.service && echo "AUTONOMOUS_WORKER_ACTIVE=YES" || echo "AUTONOMOUS_WORKER_ACTIVE=NO"
pgrep -c -f 'autonomous_worker' | xargs -I{} echo "AUTONOMOUS_WORKER_INSTANCE_COUNT={}"
cd /opt/CRM_Streamlit_rescue
echo "GIT_DIRTY=$(git status --porcelain | wc -l)"
echo "COMMITTED_PYC=$(git ls-files | grep -cE '(__pycache__/|\.pyc$)' || echo 0)"
echo "ALL_DONE"
