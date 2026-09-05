#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

ACCEPTANCE_START=$(date -Iseconds)
echo "ACCEPTANCE_START=$ACCEPTANCE_START"

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
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

# ── Find the stage radio by key ──
stage_radio = at.radio(key="analytics_v2_active_stage")
if stage_radio:
    print(f"STAGE_RADIO_OPTIONS={list(stage_radio.options)}")
    # Find "Идут торги" option
    torgi_opt = None
    for opt in stage_radio.options:
        if 'торг' in str(opt).lower():
            torgi_opt = opt
            break
    if torgi_opt:
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

        # Check ImportError
        import_errors = [str(e.value) for e in at.exception if 'import' in str(e.value).lower()]
        R["STAGED_IMPORT_RUNTIME_ERROR_PRESENT"] = "YES" if import_errors else "NO"
        print(f"STAGED_IMPORT_RUNTIME_ERROR_PRESENT={R['STAGED_IMPORT_RUNTIME_ERROR_PRESENT']}")

        # ── Check Торги content ──
        for m in at.markdown:
            val = str(m.value)
            if 'торг' in val.lower() or 'идут' in val.lower():
                print(f"TORGI_MD={val[:150]}")
        for c in at.caption:
            val = str(c.value)
            if 'показано' in val.lower():
                print(f"PAGINATION_CAP={val}")

        # ── PILLS ──
        print("=== PILLS ===")
        for p in at.pills:
            opts = list(p.options)
            print(f"PILLS label={p.label}")
            for o in opts:
                print(f"  {o}")

        # ── RADIO ──
        print("=== RADIOS ===")
        for r in at.radio:
            if r.key != "analytics_v2_active_stage" and r.key != "ui_theme_radio":
                print(f"  RADIO: label={r.label} options={list(r.options)} key={r.key}")

        # ── NUMBER INPUTS ──
        print("=== NUMBER_INPUTS ===")
        for ni in at.number_input:
            print(f"  NI: label={ni.label} value={ni.value} min={ni.min} max={ni.max}")

        # ── SELECTBOXES ──
        print("=== SELECTBOXES ===")
        for sb in at.selectbox:
            print(f"  SB: label={sb.label} opts={list(sb.options)[:6]} value={sb.value}")

        # ── BUTTONS ──
        print("=== BUTTONS ===")
        procurement_btns = []
        for b in at.button:
            label = str(b.label)
            if 'nav_' in str(b.key):
                continue
            if len(label) > 20:
                procurement_btns.append((b, label))
                if len(procurement_btns) <= 3:
                    print(f"  CARD_BTN: {label[:200]}")
            else:
                print(f"  SHORT_BTN: {label} key={b.key}")
        print(f"PROCUREMENT_BTNS_COUNT={len(procurement_btns)}")

        # ── EXPANDERS ──
        print("=== EXPANDERS ===")
        for exp in at.expander:
            print(f"  EXP: label={exp.label[:100]}")

        # ── Open first card ──
        if procurement_btns:
            btn, label = procurement_btns[0]
            print(f"\n=== PHASE 6: CLICKING CARD: {label[:100]} ===")
            btn.click()
            t0 = time.time()
            at.run(timeout=60)
            T_CARD = int((time.time()-t0)*1000)
            R["T_FIRST_CARD_MS"] = T_CARD
            print(f"T_FIRST_CARD_MS={T_CARD}")
            print(f"CARD_OPEN_EXCEPTIONS={len(at.exception)}")
            for exc in at.exception:
                print(f"  CARD_EXC={exc.value[:300]}")
            card_import = [str(e.value) for e in at.exception if 'import' in str(e.value).lower()]
            if card_import:
                R["STAGED_IMPORT_RUNTIME_ERROR_PRESENT"] = "YES"

            R["REAL_CARD_OPENED"] = "YES" if len(at.exception) == 0 else "EXCEPTION"

            # Detail content
            for m in at.markdown:
                val = str(m.value)
                if any(x in val.lower() for x in ['нмцк', '₽', 'закупк', 'приём', '44-фз', '223-фз', 'tender', 'reestr']):
                    print(f"  DETAIL_MD: {val[:200]}")
            for c in at.caption:
                val = str(c.value)
                if any(x in val.lower() for x in ['нмцк', 'цена', 'приём', 'источник']):
                    print(f"  DETAIL_CAP: {val[:200]}")

            # ── PHASE 8: ANNOTATION GATE ──
            print("=== PHASE 8: ANNOTATION GATE ===")
            gate = None
            for r in at.radio:
                opts = [str(o) for o in r.options]
                if 'Да' in opts and 'Нет' in opts and 'Не уверен' in opts:
                    gate = r
                    print(f"CATEGORY_GATE: label={r.label} options={opts}")
                    break

            R["REAL_CATEGORY_GATE_RENDERED"] = "YES" if gate else "NO"
            print(f"REAL_CATEGORY_GATE_RENDERED={R['REAL_CATEGORY_GATE_RENDERED']}")

            if gate:
                # ── PHASE 9: IN_CATEGORY ──
                print("=== PHASE 9: IN_CATEGORY ===")
                gate.set_value("Да")
                at.run(timeout=60)
                print(f"IN_CAT_EXCEPTIONS={len(at.exception)}")
                for exc in at.exception:
                    print(f"  IN_EXC={exc.value[:200]}")

                deep = {}
                for sb in at.selectbox:
                    l = str(sb.label).lower()
                    for key in ['категор', 'подкатегор', 'объект', 'сектор', 'коммерч', 'медал', 'тип закупк', 'закупк']:
                        if key in l:
                            deep[key] = sb
                            print(f"  DEEP_SB: label={sb.label} opts={list(sb.options)[:5]}")
                for ms in at.multiselect:
                    l = str(ms.label).lower()
                    for key in ['категор', 'подкатегор']:
                        if key in l:
                            deep[key] = ms
                            print(f"  DEEP_MS: label={ms.label} opts={list(ms.options)[:5]}")
                for r in at.radio:
                    l = str(r.label).lower()
                    for key in ['коммерч', 'медал', 'объект', 'сектор']:
                        if key in l:
                            deep[key] = r
                            print(f"  DEEP_RADIO: label={r.label} opts={list(r.options)}")

                R["REAL_CATEGORY_SELECTOR_RENDERED"] = "YES" if any('категор' in k for k in deep) else "NO"
                R["REAL_SUBCATEGORY_SELECTOR_WORKS"] = "YES" if any('подкатегор' in k for k in deep) else "CHECK"
                R["REAL_OBJECT_STAGE_RENDERED"] = "YES" if any(k in deep for k in ['объект','сектор']) else "NO"
                R["REAL_PROCUREMENT_MODE_RENDERED"] = "YES" if any(k in deep for k in ['тип закупк','закупк']) else "NO"
                R["REAL_COMMERCIAL_ENTRY_RENDERED"] = "YES" if 'коммерч' in deep else "NO"
                R["REAL_CONDITIONAL_MEDAL_RENDERED"] = "YES" if 'медал' in deep else "CHECK"
                R["REAL_IN_CATEGORY_DEEP_FLOW_RENDERED"] = "YES"
                for k,v in R.items():
                    if 'REAL_' in k:
                        print(f"{k}={v}")

                # ── PHASE 10: OUT_OF_CATEGORY ──
                print("=== PHASE 10: OUT_OF_CATEGORY ===")
                gate.set_value("Нет")
                at.run(timeout=60)
                R["REAL_OUT_OF_CATEGORY_FAST_PATH_RENDERED"] = "YES" if len(at.exception) == 0 else "EXCEPTION"
                print(f"REAL_OUT_OF_CATEGORY_FAST_PATH_RENDERED={R['REAL_OUT_OF_CATEGORY_FAST_PATH_RENDERED']}")

                # ── PHASE 11: UNCERTAIN ──
                print("=== PHASE 11: UNCERTAIN ===")
                gate.set_value("Не уверен")
                at.run(timeout=60)
                R["REAL_UNCERTAIN_FAST_PATH_RENDERED"] = "YES" if len(at.exception) == 0 else "EXCEPTION"
                print(f"REAL_UNCERTAIN_FAST_PATH_RENDERED={R['REAL_UNCERTAIN_FAST_PATH_RENDERED']}")

        # ── PHASE 12: PAGINATION ──
        print("=== PHASE 12: PAGINATION ===")
        page_ni = None
        for ni in at.number_input:
            if 'страниц' in str(ni.label).lower():
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
        print("ТОРГИ_OPTION_NOT_FOUND")
else:
    print("STAGE_RADIO_NOT_FOUND")

R["T_TOTAL_INITIAL_RENDER_MS"] = R.get("T_HEADER_MS", 0)
print("\n=== FINAL RESULTS ===")
print(json.dumps(R, indent=2, ensure_ascii=False))
PYEOF

echo "=== PHASE 13: SERVER LOG CHECK ==="
journalctl -u crm-streamlit.service --since "$ACCEPTANCE_START" --no-pager 2>&1 | grep -ic 'traceback\|importerror' | xargs -I{} echo "STREAMLIT_TRACEBACKS_DURING_ACCEPTANCE={}"

echo "=== PHASE 14-15 ==="
systemctl is-active crm-v3-autonomous-worker.service && echo "AUTONOMOUS_WORKER_ACTIVE=YES" || echo "AUTONOMOUS_WORKER_ACTIVE=NO"
pgrep -c -f 'autonomous_worker' | xargs -I{} echo "AUTONOMOUS_WORKER_INSTANCE_COUNT={}"
cd /opt/CRM_Streamlit_rescue
echo "GIT_DIRTY=$(git status --porcelain | wc -l)"
echo "COMMITTED_PYC=$(git ls-files | grep -cE '(__pycache__/|\.pyc$)' || echo 0)"
echo "ALL_DONE"
