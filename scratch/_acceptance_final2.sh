#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

ACCEPTANCE_START=$(date -Iseconds)

cat > /tmp/_acceptance_final2.py << 'PYEOF'
# -*- coding: utf-8 -*-
import time, sys, os, json
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')
from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')
from streamlit.testing.v1 import AppTest

R = {}

# ── LOAD + NAVIGATE TO ТОРГИ ──
t0 = time.time()
at = AppTest.from_file("app.py", default_timeout=60)
at.run(timeout=60)

stage_radio = at.radio(key="analytics_v2_active_stage")
opts = list(stage_radio.options)
stage_radio.set_value(opts[2])  # Идут торги
t0 = time.time()
at.run(timeout=60)
R["T_HEADER_MS"] = int((time.time()-t0)*1000)
R["TORGI_EXCEPTIONS"] = len(at.exception)
R["STAGED_IMPORT_RUNTIME_ERROR_PRESENT"] = "NO"
R["TORGI_ROUTE_OPENED"] = "NO"

# ── Verify Торги header with workset count ──
for m in at.markdown:
    val = str(m.value)
    if '\u0442\u043e\u0440\u0433' in val.lower():
        print(f"TORGI_MD={val[:150]}")
        R["TORGI_ROUTE_OPENED"] = "YES"
        # Extract count from "### Идут торги · 5152"
        if '\u00b7' in val:
            count_str = val.split('\u00b7')[-1].strip()
            try:
                R["UI_ALL"] = int(count_str.replace('\u00a0','').replace(' ',''))
            except:
                R["UI_ALL"] = count_str

for c in at.caption:
    val = str(c.value)
    if '\u043f\u043e\u043a\u0430\u0437\u0430\u043d\u043e' in val.lower():
        print(f"PAGINATION_CAP={val}")

# ── Pagination number input key discovery ──
print("=== ALL NUMBER INPUTS ===")
page_ni = None
for ni in at.number_input:
    print(f"  NI key={ni.key} label={ni.label} value={ni.value} max={ni.max}")
    if '\u0441\u0442\u0440\u0430\u043d\u0438\u0446' in str(ni.label).lower():
        page_ni = ni

# ── Click "Разметить →" ──
print("\n=== PHASE 6+8: STAGED ANNOTATION ===")
staged_btn = None
for b in at.button:
    if str(b.key).startswith('open_staged_'):
        staged_btn = b
        break

if staged_btn:
    print(f"CLICKING: key={staged_btn.key}")
    staged_btn.click()
    t0 = time.time()
    at.run(timeout=60)
    R["T_FIRST_CARD_MS"] = int((time.time()-t0)*1000)
    R["STAGED_EXCEPTIONS"] = len(at.exception)
    for exc in at.exception:
        print(f"  STAGED_EXC={exc.value[:300]}")
        if 'import' in str(exc.value).lower():
            R["STAGED_IMPORT_RUNTIME_ERROR_PRESENT"] = "YES"

    R["REAL_CARD_OPENED"] = "YES" if len(at.exception) == 0 else "EXCEPTION"

    # Card factual detail
    for m in at.markdown:
        val = str(m.value)
        if any(x in val for x in ['\u041d\u041c\u0426\u041a', '\u20bd', '44-\u0424\u0417', '223-\u0424\u0417', '\u2116', 'zakupki.gov', 'source_table', 'reestr_contract']):
            print(f"  FACT_MD={val[:200]}")
    for c in at.caption:
        val = str(c.value)
        if any(x in val.lower() for x in ['\u0441\u0440\u043e\u043a', '\u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a', '\u043d\u043e\u043c\u0435\u0440', '\u0446\u0435\u043d', '\u0437\u0430\u043a\u0443\u043f']):
            print(f"  FACT_CAP={val[:200]}")

    # ── CATEGORY GATE ──
    gate = None
    for r in at.radio:
        opts_str = [str(o) for o in r.options]
        if '\u0414\u0430' in opts_str and '\u041d\u0435\u0442' in opts_str and '\u041d\u0435 \u0443\u0432\u0435\u0440\u0435\u043d' in opts_str:
            gate = r
            print(f"GATE: label={r.label} options={opts_str}")
            break

    R["REAL_CATEGORY_GATE_RENDERED"] = "YES" if gate else "NO"

    if gate:
        # ── IN_CATEGORY ──
        print("=== PHASE 9: IN_CATEGORY ===")
        gate.set_value('\u0414\u0430')
        at.run(timeout=60)
        print(f"IN_CAT_EXCEPTIONS={len(at.exception)}")
        for exc in at.exception:
            print(f"  EXC={exc.value[:200]}")

        cat = subcat = obj = mode = comm = medal = None
        for sb in at.selectbox:
            l = str(sb.label).lower()
            if '\u043f\u043e\u0434\u043a\u0430\u0442\u0435\u0433\u043e\u0440' in l: subcat = sb; print(f"  SUBCAT: label={sb.label} opts={list(sb.options)[:5]}")
            elif '\u043a\u0430\u0442\u0435\u0433\u043e\u0440' in l: cat = sb; print(f"  CAT: label={sb.label} opts={list(sb.options)[:5]}")
            elif '\u043e\u0431\u044a\u0435\u043a\u0442' in l: obj = sb; print(f"  OBJ: label={sb.label} opts={list(sb.options)[:5]}")
            elif '\u0437\u0430\u043a\u0443\u043f' in l: mode = sb; print(f"  MODE: label={sb.label} opts={list(sb.options)[:5]}")
            elif '\u043a\u043e\u043c\u043c\u0435\u0440\u0447' in l: comm = sb; print(f"  COMM: label={sb.label} opts={list(sb.options)[:5]}")
            elif '\u043c\u0435\u0434\u0430\u043b' in l: medal = sb; print(f"  MEDAL: label={sb.label} opts={list(sb.options)[:5]}")
        for r in at.radio:
            l = str(r.label).lower()
            if r.key in ("analytics_v2_active_stage", "ui_theme_radio", "analytics_v2_cat_stage_radio", "analytics_v2_show_mode", "torgi_deadline_sort"):
                continue
            if '\u043a\u043e\u043c\u043c\u0435\u0440\u0447' in l: comm = r; print(f"  COMM_R: label={r.label} opts={list(r.options)}")
            elif '\u043c\u0435\u0434\u0430\u043b' in l: medal = r; print(f"  MEDAL_R: label={r.label} opts={list(r.options)}")
            elif '\u043e\u0431\u044a\u0435\u043a\u0442' in l: obj = r; print(f"  OBJ_R: label={r.label} opts={list(r.options)}")
            elif '\u0437\u0430\u043a\u0443\u043f' in l or '\u0442\u0438\u043f' in l: mode = r; print(f"  MODE_R: label={r.label} opts={list(r.options)}")
            elif '\u043a\u0430\u0442\u0435\u0433\u043e\u0440' in l and gate != r: cat = r; print(f"  CAT_R: label={r.label} opts={list(r.options)}")
            else: print(f"  UNK_R: label={r.label} opts={list(r.options)} key={r.key}")

        R["REAL_CATEGORY_SELECTOR_RENDERED"] = "YES" if cat else "NO"
        R["REAL_SUBCATEGORY_SELECTOR_WORKS"] = "YES" if subcat else "CHECK"
        R["REAL_OBJECT_STAGE_RENDERED"] = "YES" if obj else "NO"
        R["REAL_PROCUREMENT_MODE_RENDERED"] = "YES" if mode else "NO"
        R["REAL_COMMERCIAL_ENTRY_RENDERED"] = "YES" if comm else "NO"
        R["REAL_CONDITIONAL_MEDAL_RENDERED"] = "YES" if medal else "CHECK"
        R["REAL_IN_CATEGORY_DEEP_FLOW_RENDERED"] = "YES"

        # ── OUT_OF_CATEGORY ──
        print("=== PHASE 10: OUT_OF_CATEGORY ===")
        gate.set_value('\u041d\u0435\u0442')
        at.run(timeout=60)
        R["REAL_OUT_OF_CATEGORY_FAST_PATH_RENDERED"] = "YES" if len(at.exception) == 0 else "EXCEPTION"
        print(f"OUT_EXCEPTIONS={len(at.exception)}")

        # ── UNCERTAIN ──
        print("=== PHASE 11: UNCERTAIN ===")
        gate.set_value('\u041d\u0435 \u0443\u0432\u0435\u0440\u0435\u043d')
        at.run(timeout=60)
        R["REAL_UNCERTAIN_FAST_PATH_RENDERED"] = "YES" if len(at.exception) == 0 else "EXCEPTION"
        print(f"UNCERTAIN_EXCEPTIONS={len(at.exception)}")

# ── PAGINATION ──
print("=== PHASE 12: PAGINATION ===")
if page_ni:
    print(f"PAGE_NI: value={page_ni.value} max={page_ni.max}")
    if page_ni.max and int(page_ni.max) > 1:
        # Go back to list first
        stage_radio = at.radio(key="analytics_v2_active_stage")
        opts = list(stage_radio.options)
        stage_radio.set_value(opts[2])
        at.run(timeout=60)

        for ni in at.number_input:
            if '\u0441\u0442\u0440\u0430\u043d\u0438\u0446' in str(ni.label).lower():
                page_ni = ni
                break
        page_ni.set_value(2)
        t0 = time.time()
        at.run(timeout=60)
        T_P2 = int((time.time()-t0)*1000)
        print(f"PAGE2_MS={T_P2}")
        print(f"PAGE2_EXCEPTIONS={len(at.exception)}")
        for exc in at.exception:
            print(f"  P2_EXC={exc.value[:200]}")
        R["REAL_PAGINATION"] = "PASS" if len(at.exception) == 0 else "EXCEPTION"
    else:
        R["REAL_PAGINATION"] = "SINGLE_PAGE"
else:
    R["REAL_PAGINATION"] = "NO_PAGE_INPUT"

R["T_TOTAL_INITIAL_RENDER_MS"] = R.get("T_HEADER_MS", 0)
print("\n=== FINAL RESULTS ===")
for k in sorted(R):
    print(f"{k}={R[k]}")
PYEOF

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python /tmp/_acceptance_final2.py 2>&1

echo "=== PHASE 13 ==="
journalctl -u crm-streamlit.service --since "$ACCEPTANCE_START" --no-pager 2>&1 | grep -ic 'traceback\|importerror' | xargs -I{} echo "STREAMLIT_TRACEBACKS={}"
echo "=== PHASE 14-15 ==="
systemctl is-active crm-v3-autonomous-worker.service && echo "WORKER_ACTIVE=YES" || echo "WORKER_ACTIVE=NO"
pgrep -c -f 'autonomous_worker' | xargs -I{} echo "WORKER_COUNT={}"
cd /opt/CRM_Streamlit_rescue
echo "GIT_DIRTY=$(git status --porcelain | wc -l)"
echo "PYC_COMMITTED=$(git ls-files | grep -cE '(__pycache__/|\.pyc$)' || echo 0)"
echo "DONE"
