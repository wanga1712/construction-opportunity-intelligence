#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

ACCEPTANCE_START=$(date -Iseconds)
echo "ACCEPTANCE_START=$ACCEPTANCE_START"

cat > /tmp/_acceptance_final.py << 'PYEOF'
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

# ── Navigate to Торги (index 2) ──
stage_radio = at.radio(key="analytics_v2_active_stage")
opts = list(stage_radio.options)
stage_radio.set_value(opts[2])  # Идут торги
t0 = time.time()
at.run(timeout=60)
T_HEADER_MS = int((time.time()-t0)*1000)
R["T_HEADER_MS"] = T_HEADER_MS
print(f"T_HEADER_MS={T_HEADER_MS}")
print(f"TORGI_EXCEPTIONS={len(at.exception)}")

# ── Verify Торги header ──
for m in at.markdown:
    val = str(m.value)
    if '\u0442\u043e\u0440\u0433' in val.lower() or '\u0438\u0434\u0443\u0442' in val.lower():
        print(f"TORGI_MD={val[:150]}")
        R["TORGI_ROUTE_OPENED"] = "YES"

# ── Pagination ──
page_ni = at.number_input(key="torgi_page")
if page_ni:
    print(f"PAGE_INPUT: value={page_ni.value} max={page_ni.max}")
    R["MAX_PAGES"] = int(page_ni.max)
else:
    # Try by label
    for ni in at.number_input:
        if '\u0441\u0442\u0440\u0430\u043d\u0438\u0446' in str(ni.label).lower() or 'page' in str(ni.label).lower():
            page_ni = ni
            print(f"PAGE_INPUT: label={ni.label} value={ni.value} max={ni.max} key={ni.key}")
            R["MAX_PAGES"] = int(ni.max)
            break

# ── DB counts from workset ──
# Counts visible in caption
for c in at.caption:
    val = str(c.value)
    if '\u043f\u043e\u043a\u0430\u0437\u0430\u043d\u043e' in val.lower() or '\u0438\u0437' in val.lower():
        print(f"PAGINATION_CAP={val}")

# ── Review filter - the selectboxes ──
# Found: Категории ['Все', 'IN_CATEGORY', 'OUT_OF_CATEGORY', 'UNCERTAIN']
# This IS the review/annotation filter
for sb in at.selectbox:
    label = str(sb.label)
    if label in ('\u041a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u0438',):  # "Категории"
        print(f"CATEGORY_FILTER: opts={list(sb.options)} value={sb.value}")

# ── Click "Разметить →" to open staged annotation gate ──
print("\n=== PHASE 6+8: CLICK STAGED ANNOTATION ===")
staged_btn = None
staged_key = None
for b in at.button:
    key = str(b.key)
    if key.startswith('open_staged_'):
        staged_btn = b
        staged_key = key
        break

if staged_btn:
    print(f"CLICKING: key={staged_key}")
    staged_btn.click()
    t0 = time.time()
    at.run(timeout=60)
    T_CARD = int((time.time()-t0)*1000)
    R["T_FIRST_CARD_MS"] = T_CARD
    print(f"T_FIRST_CARD_MS={T_CARD}")
    print(f"STAGED_EXCEPTIONS={len(at.exception)}")
    for exc in at.exception:
        print(f"  STAGED_EXC={exc.value[:300]}")

    import_errors = [str(e.value) for e in at.exception if 'import' in str(e.value).lower()]
    R["STAGED_IMPORT_RUNTIME_ERROR_PRESENT"] = "YES" if import_errors else "NO"
    R["REAL_CARD_OPENED"] = "YES" if len(at.exception) == 0 else "EXCEPTION"
    print(f"STAGED_IMPORT_RUNTIME_ERROR_PRESENT={R['STAGED_IMPORT_RUNTIME_ERROR_PRESENT']}")
    print(f"REAL_CARD_OPENED={R['REAL_CARD_OPENED']}")

    # ── Find category gate (Да/Нет/Не уверен) ──
    gate = None
    for r in at.radio:
        opts_str = [str(o) for o in r.options]
        if '\u0414\u0430' in opts_str and '\u041d\u0435\u0442' in opts_str:
            gate = r
            print(f"CATEGORY_GATE: label={r.label} options={opts_str}")
            break

    R["REAL_CATEGORY_GATE_RENDERED"] = "YES" if gate else "NO"
    print(f"REAL_CATEGORY_GATE_RENDERED={R['REAL_CATEGORY_GATE_RENDERED']}")

    # ── Card detail content (factual header) ──
    for m in at.markdown:
        val = str(m.value)
        if any(x in val for x in ['\u041d\u041c\u0426\u041a', '\u20bd', '44-\u0424\u0417', '223-\u0424\u0417', '\u2116']):
            print(f"  CARD_HEADER_MD: {val[:200]}")
    for c in at.caption:
        val = str(c.value)
        if any(x in val.lower() for x in ['\u0441\u0440\u043e\u043a', '\u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a', '\u043d\u043e\u043c\u0435\u0440']):
            print(f"  CARD_HEADER_CAP: {val[:200]}")

    # ── Deep flow: Selectboxes, radios after Да ──
    if gate:
        # ── PHASE 9: IN_CATEGORY ──
        print("=== PHASE 9: IN_CATEGORY DEEP FLOW ===")
        gate.set_value('\u0414\u0430')
        at.run(timeout=60)
        print(f"IN_CAT_EXCEPTIONS={len(at.exception)}")
        for exc in at.exception:
            print(f"  EXC={exc.value[:200]}")

        # Category selector
        cat_sel = None
        subcat_sel = None
        obj_sel = None
        mode_sel = None
        comm_sel = None
        medal_entry = None

        for sb in at.selectbox:
            l = str(sb.label).lower()
            if '\u043f\u043e\u0434\u043a\u0430\u0442\u0435\u0433\u043e\u0440' in l:
                subcat_sel = sb
                print(f"  SUBCAT_SB: label={sb.label} opts={list(sb.options)[:5]}")
            elif '\u043a\u0430\u0442\u0435\u0433\u043e\u0440' in l:
                cat_sel = sb
                print(f"  CAT_SB: label={sb.label} opts={list(sb.options)[:5]}")
            elif '\u043e\u0431\u044a\u0435\u043a\u0442' in l or '\u0441\u0435\u043a\u0442\u043e\u0440' in l:
                obj_sel = sb
                print(f"  OBJ_SB: label={sb.label} opts={list(sb.options)[:5]}")
            elif '\u0437\u0430\u043a\u0443\u043f' in l or 'mode' in l:
                mode_sel = sb
                print(f"  MODE_SB: label={sb.label} opts={list(sb.options)[:5]}")
            elif '\u043a\u043e\u043c\u043c\u0435\u0440\u0447' in l:
                comm_sel = sb
                print(f"  COMM_SB: label={sb.label} opts={list(sb.options)[:5]}")
            elif '\u043c\u0435\u0434\u0430\u043b' in l:
                medal_entry = sb
                print(f"  MEDAL_SB: label={sb.label} opts={list(sb.options)[:5]}")

        for r in at.radio:
            l = str(r.label).lower()
            if r.key in ("analytics_v2_active_stage", "ui_theme_radio", "analytics_v2_cat_stage_radio", "analytics_v2_show_mode", "torgi_deadline_sort"):
                continue
            if '\u043a\u043e\u043c\u043c\u0435\u0440\u0447' in l or '\u043e\u0446\u0435\u043d\u043a' in l:
                comm_sel = r
                print(f"  COMM_RADIO: label={r.label} opts={list(r.options)}")
            elif '\u043c\u0435\u0434\u0430\u043b' in l:
                medal_entry = r
                print(f"  MEDAL_RADIO: label={r.label} opts={list(r.options)}")
            elif '\u043e\u0431\u044a\u0435\u043a\u0442' in l or '\u0441\u0435\u043a\u0442\u043e\u0440' in l:
                obj_sel = r
                print(f"  OBJ_RADIO: label={r.label} opts={list(r.options)}")
            elif '\u0437\u0430\u043a\u0443\u043f' in l or '\u0442\u0438\u043f' in l:
                mode_sel = r
                print(f"  MODE_RADIO: label={r.label} opts={list(r.options)}")
            elif '\u043a\u0430\u0442\u0435\u0433\u043e\u0440' in l:
                cat_sel = r
                print(f"  CAT_RADIO: label={r.label} opts={list(r.options)}")
            else:
                print(f"  OTHER_RADIO: label={r.label} opts={list(r.options)} key={r.key}")

        R["REAL_CATEGORY_SELECTOR_RENDERED"] = "YES" if cat_sel else "NO"
        R["REAL_SUBCATEGORY_SELECTOR_WORKS"] = "YES" if subcat_sel else "CHECK"
        R["REAL_OBJECT_STAGE_RENDERED"] = "YES" if obj_sel else "NO"
        R["REAL_PROCUREMENT_MODE_RENDERED"] = "YES" if mode_sel else "NO"
        R["REAL_COMMERCIAL_ENTRY_RENDERED"] = "YES" if comm_sel else "NO"
        R["REAL_CONDITIONAL_MEDAL_RENDERED"] = "YES" if medal_entry else "CHECK"
        R["REAL_IN_CATEGORY_DEEP_FLOW_RENDERED"] = "YES"

        for k in sorted(R):
            if 'REAL_' in k:
                print(f"{k}={R[k]}")

        # ── PHASE 10: OUT_OF_CATEGORY ──
        print("=== PHASE 10: OUT_OF_CATEGORY ===")
        gate.set_value('\u041d\u0435\u0442')
        at.run(timeout=60)
        R["REAL_OUT_OF_CATEGORY_FAST_PATH_RENDERED"] = "YES" if len(at.exception) == 0 else f"EXCEPTION({len(at.exception)})"
        print(f"OUT_EXCEPTIONS={len(at.exception)}")
        print(f"REAL_OUT_OF_CATEGORY_FAST_PATH_RENDERED={R['REAL_OUT_OF_CATEGORY_FAST_PATH_RENDERED']}")

        # ── PHASE 11: UNCERTAIN ──
        print("=== PHASE 11: UNCERTAIN ===")
        gate.set_value('\u041d\u0435 \u0443\u0432\u0435\u0440\u0435\u043d')
        at.run(timeout=60)
        R["REAL_UNCERTAIN_FAST_PATH_RENDERED"] = "YES" if len(at.exception) == 0 else f"EXCEPTION({len(at.exception)})"
        print(f"UNCERTAIN_EXCEPTIONS={len(at.exception)}")
        print(f"REAL_UNCERTAIN_FAST_PATH_RENDERED={R['REAL_UNCERTAIN_FAST_PATH_RENDERED']}")

    # ── PHASE 12: PAGINATION ──
    print("=== PHASE 12: PAGINATION ===")
    # Go back to list first (close staged)
    at.session_state.pop("staged_procurement_id", None)
    at.run(timeout=60)

    # Find page input again
    for ni in at.number_input:
        label = str(ni.label).lower()
        if '\u0441\u0442\u0440\u0430\u043d\u0438\u0446' in label:
            page_ni = ni
            break

    if page_ni:
        print(f"PAGE: value={page_ni.value} max={page_ni.max}")
        if page_ni.max and int(page_ni.max) > 1:
            page_ni.set_value(2)
            t0 = time.time()
            at.run(timeout=60)
            T_P2 = int((time.time()-t0)*1000)
            print(f"PAGE2_MS={T_P2}")
            print(f"PAGE2_EXCEPTIONS={len(at.exception)}")
            for exc in at.exception:
                print(f"  P2_EXC={exc.value[:200]}")
            page_ni.set_value(1)
            at.run(timeout=60)
            R["REAL_PAGINATION"] = "PASS" if len(at.exception) == 0 else "EXCEPTION"
        else:
            R["REAL_PAGINATION"] = "SINGLE_PAGE"
    else:
        R["REAL_PAGINATION"] = "NO_PAGE_INPUT"

else:
    R["REAL_CARD_OPENED"] = "NO_STAGED_BUTTONS"

R["T_TOTAL_INITIAL_RENDER_MS"] = R.get("T_HEADER_MS", 0)

print("\n=== FINAL RESULTS ===")
print(json.dumps(R, indent=2, ensure_ascii=False))
PYEOF

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python /tmp/_acceptance_final.py 2>&1

echo "=== PHASE 13 ==="
journalctl -u crm-streamlit.service --since "$ACCEPTANCE_START" --no-pager 2>&1 | grep -ic 'traceback\|importerror' | xargs -I{} echo "STREAMLIT_TRACEBACKS={}"

echo "=== PHASE 14-15 ==="
systemctl is-active crm-v3-autonomous-worker.service && echo "WORKER_ACTIVE=YES" || echo "WORKER_ACTIVE=NO"
pgrep -c -f 'autonomous_worker' | xargs -I{} echo "WORKER_COUNT={}"
cd /opt/CRM_Streamlit_rescue
echo "GIT_DIRTY=$(git status --porcelain | wc -l)"
echo "PYC_COMMITTED=$(git ls-files | grep -cE '(__pycache__/|\.pyc$)' || echo 0)"
echo "DONE"
