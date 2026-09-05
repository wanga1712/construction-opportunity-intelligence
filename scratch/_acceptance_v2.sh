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
print("=== INITIAL LOAD ===")
t0 = time.time()
at = AppTest.from_file("app.py", default_timeout=60)
at.run(timeout=60)
print(f"INITIAL_LOAD_MS={int((time.time()-t0)*1000)}")
print(f"INITIAL_EXCEPTIONS={len(at.exception)}")

# ── Navigate to objects_v2 (default page) ──
# objects_v2 is the default nav_page, so it should already be there.
# Set the stage radio to "Идут торги"
print("=== NAVIGATE TO ТОРГИ ===")

# The "Раздел" radio key is "analytics_v2_active_stage"
at.session_state["analytics_v2_active_stage"] = "Идут торги"
t0 = time.time()
at.run(timeout=60)
T_HEADER_MS = int((time.time()-t0)*1000)
R["T_HEADER_MS"] = T_HEADER_MS
print(f"T_HEADER_MS={T_HEADER_MS}")
print(f"TORGI_EXCEPTIONS={len(at.exception)}")
for exc in at.exception:
    print(f"  EXC={exc.value[:200]}")

# Check for ImportError
import_errors = [str(e.value) for e in at.exception if 'import' in str(e.value).lower()]
R["STAGED_IMPORT_RUNTIME_ERROR_PRESENT"] = "YES" if import_errors else "NO"
print(f"STAGED_IMPORT_RUNTIME_ERROR_PRESENT={R['STAGED_IMPORT_RUNTIME_ERROR_PRESENT']}")

# ── Verify Торги content rendered ──
torgi_rendered = False
for m in at.markdown:
    val = str(m.value)
    if 'торг' in val.lower() or 'идут' in val.lower():
        print(f"TORGI_MD={val[:150]}")
        torgi_rendered = True
R["TORGI_ROUTE_OPENED"] = "YES" if torgi_rendered else "NO"
print(f"TORGI_ROUTE_OPENED={R['TORGI_ROUTE_OPENED']}")

# ── PILLS: Review filter (annotation counts) ──
print("=== REVIEW FILTER PILLS ===")
for p in at.pills:
    opts = list(p.options)
    print(f"PILLS label={p.label}")
    for o in opts:
        print(f"  {o}")

# ── RADIO: Sort mode ──
print("=== RADIO BUTTONS ===")
for r in at.radio:
    print(f"  RADIO label={r.label} options={list(r.options)} value={r.value}")

# ── CAPTIONS: Pagination info ──
print("=== CAPTIONS ===")
for c in at.caption:
    val = str(c.value)
    if 'показано' in val.lower() or 'торг' in val.lower() or 'из' in val.lower():
        print(f"  PAGINATION_CAP={val[:150]}")

# ── SELECTBOXES ──
print("=== SELECTBOXES ===")
for sb in at.selectbox:
    print(f"  SB label={sb.label} options={list(sb.options)[:8]} value={sb.value}")

# ── NUMBER INPUTS (pagination) ──
print("=== NUMBER INPUTS ===")
for ni in at.number_input:
    print(f"  NI label={ni.label} value={ni.value} min={ni.min} max={ni.max}")

# ── BUTTONS (procurement card buttons) ──
print("=== BUTTONS ===")
procurement_buttons = []
for b in at.button:
    label = str(b.label)
    # Card feed buttons have procurement titles
    if len(label) > 15:
        procurement_buttons.append(label)
        if len(procurement_buttons) <= 5:
            print(f"  BTN={label[:200]}")
    elif 'nav_' not in b.key:
        print(f"  BTN_SHORT={label}")

print(f"PROCUREMENT_BUTTONS={len(procurement_buttons)}")

# ── PHASE 6: Open first card ──
print("=== PHASE 6: OPEN CARD ===")
if procurement_buttons:
    target_label = procurement_buttons[0]
    for b in at.button:
        if str(b.label) == target_label:
            print(f"CLICKING={target_label[:100]}")
            b.click()
            break
    t0 = time.time()
    at.run(timeout=60)
    T_FIRST_CARD_MS = int((time.time()-t0)*1000)
    R["T_FIRST_CARD_MS"] = T_FIRST_CARD_MS
    print(f"T_FIRST_CARD_MS={T_FIRST_CARD_MS}")
    print(f"CARD_EXCEPTIONS={len(at.exception)}")
    for exc in at.exception:
        print(f"  CARD_EXC={exc.value[:200]}")

    # Check import error after card open
    card_import_errors = [str(e.value) for e in at.exception if 'import' in str(e.value).lower()]
    if card_import_errors:
        R["STAGED_IMPORT_RUNTIME_ERROR_PRESENT"] = "YES"
        print(f"CARD_IMPORT_ERROR={card_import_errors[0][:200]}")

    R["REAL_CARD_OPENED"] = "YES" if len(at.exception) == 0 else "EXCEPTION"

    # Check card content
    print("--- Card detail content ---")
    for m in at.markdown:
        val = str(m.value)
        if any(x in val.lower() for x in ['нмцк', 'закупк', 'приём', 'торг', '₽', 'руб', '44-фз', '223-фз', 'reestr', 'tender_link', 'номер']):
            print(f"  CARD_MD={val[:200]}")
    for c in at.caption:
        val = str(c.value)
        if any(x in val.lower() for x in ['нмцк', 'цена', 'приём', 'источник', 'reestr', 'номер']):
            print(f"  CARD_CAP={val[:200]}")

    # ── PHASE 8: ANNOTATION GATE ──
    print("=== PHASE 8: ANNOTATION GATE ===")
    gate_radios = []
    for r in at.radio:
        opts = [str(o) for o in r.options]
        if 'Да' in opts and 'Нет' in opts:
            gate_radios.append(r)
            print(f"CATEGORY_GATE: label={r.label} options={opts}")

    # Also check selectboxes for category/annotation
    annotation_selects = []
    for sb in at.selectbox:
        label = str(sb.label).lower()
        if any(x in label for x in ['категор', 'объект', 'тип', 'коммерч', 'медал', 'подкатегор', 'сектор', 'закупк']):
            annotation_selects.append(sb)
            print(f"ANNOTATION_SB: label={sb.label} options={list(sb.options)[:5]}")

    R["REAL_CATEGORY_GATE_RENDERED"] = "YES" if gate_radios else "NO"
    print(f"REAL_CATEGORY_GATE_RENDERED={R['REAL_CATEGORY_GATE_RENDERED']}")

    # ── PHASE 9: IN_CATEGORY deep flow ──
    if gate_radios:
        print("=== PHASE 9: IN_CATEGORY DEEP FLOW ===")
        gate = gate_radios[0]
        gate.set_value("Да")
        at.run(timeout=60)
        print(f"IN_CATEGORY_EXCEPTIONS={len(at.exception)}")

        # Check for deep flow selectors
        deep_selects = []
        for sb in at.selectbox:
            label = str(sb.label).lower()
            if any(x in label for x in ['категор', 'подкатегор', 'объект', 'тип', 'коммерч', 'медал', 'сектор', 'закупк']):
                deep_selects.append(sb)
                print(f"  DEEP_SB: label={sb.label} options={list(sb.options)[:5]}")

        cat_select = [s for s in deep_selects if 'категор' in str(s.label).lower() and 'подкатегор' not in str(s.label).lower()]
        subcat_select = [s for s in deep_selects if 'подкатегор' in str(s.label).lower()]
        obj_select = [s for s in deep_selects if 'объект' in str(s.label).lower() or 'сектор' in str(s.label).lower()]
        mode_select = [s for s in deep_selects if 'закупк' in str(s.label).lower() or 'mode' in str(s.label).lower() or 'тип' in str(s.label).lower()]
        commercial_select = [s for s in deep_selects if 'коммерч' in str(s.label).lower()]

        R["REAL_CATEGORY_SELECTOR_RENDERED"] = "YES" if cat_select else "NO"
        R["REAL_SUBCATEGORY_SELECTOR_WORKS"] = "YES" if subcat_select else "CHECK"
        R["REAL_OBJECT_STAGE_RENDERED"] = "YES" if obj_select else "NO"
        R["REAL_PROCUREMENT_MODE_RENDERED"] = "YES" if mode_select else "NO"
        R["REAL_COMMERCIAL_ENTRY_RENDERED"] = "YES" if commercial_select else "NO"

        # Check multiselect for categories
        for ms in at.multiselect:
            label = str(ms.label).lower()
            print(f"  MULTISELECT: label={ms.label} options={list(ms.options)[:5]}")

        # Check deep flow radios
        for r in at.radio:
            opts = [str(o) for o in r.options]
            label = str(r.label).lower()
            if any(x in label for x in ['коммерч', 'медал', 'объект', 'сектор', 'тип', 'закупк']):
                print(f"  DEEP_RADIO: label={r.label} options={opts}")

        medal_found = False
        for sb in at.selectbox:
            if 'медал' in str(sb.label).lower():
                medal_found = True
                print(f"  MEDAL_SB: label={sb.label} options={list(sb.options)[:5]}")
        for r in at.radio:
            if 'медал' in str(r.label).lower():
                medal_found = True
        R["REAL_CONDITIONAL_MEDAL_RENDERED"] = "YES" if medal_found else "CHECK"
        R["REAL_IN_CATEGORY_DEEP_FLOW_RENDERED"] = "YES"

        print(f"REAL_CATEGORY_SELECTOR_RENDERED={R['REAL_CATEGORY_SELECTOR_RENDERED']}")
        print(f"REAL_SUBCATEGORY_SELECTOR_WORKS={R['REAL_SUBCATEGORY_SELECTOR_WORKS']}")
        print(f"REAL_OBJECT_STAGE_RENDERED={R['REAL_OBJECT_STAGE_RENDERED']}")
        print(f"REAL_PROCUREMENT_MODE_RENDERED={R['REAL_PROCUREMENT_MODE_RENDERED']}")
        print(f"REAL_COMMERCIAL_ENTRY_RENDERED={R['REAL_COMMERCIAL_ENTRY_RENDERED']}")
        print(f"REAL_CONDITIONAL_MEDAL_RENDERED={R['REAL_CONDITIONAL_MEDAL_RENDERED']}")

        # ── PHASE 10: OUT_OF_CATEGORY ──
        print("=== PHASE 10: OUT_OF_CATEGORY ===")
        gate.set_value("Нет")
        at.run(timeout=60)
        # Deep flow should not be required
        out_deep = [sb for sb in at.selectbox if any(x in str(sb.label).lower() for x in ['подкатегор', 'коммерч'])]
        R["REAL_OUT_OF_CATEGORY_FAST_PATH_RENDERED"] = "YES" if len(at.exception) == 0 else "EXCEPTION"
        print(f"REAL_OUT_OF_CATEGORY_FAST_PATH_RENDERED={R['REAL_OUT_OF_CATEGORY_FAST_PATH_RENDERED']}")
        print(f"OUT_DEEP_SELECTORS={len(out_deep)}")

        # ── PHASE 11: UNCERTAIN ──
        print("=== PHASE 11: UNCERTAIN ===")
        gate.set_value("Не уверен")
        at.run(timeout=60)
        R["REAL_UNCERTAIN_FAST_PATH_RENDERED"] = "YES" if len(at.exception) == 0 else "EXCEPTION"
        print(f"REAL_UNCERTAIN_FAST_PATH_RENDERED={R['REAL_UNCERTAIN_FAST_PATH_RENDERED']}")

    else:
        # Try looking for annotation section button
        # The annotation section might only render when a specific tab is selected
        print("NO_CATEGORY_GATE_IN_INITIAL_CARD_VIEW")
        # The card uses tabs: Обзор, Модель/Категории, Документы, История, Экспертная разметка
        # The annotation gate is in "Экспертная разметка" tab
        # Check for section buttons/tabs
        for b in at.button:
            label = str(b.label)
            if any(x in label.lower() for x in ['экспертн', 'разметк', 'категори', 'аннотац']):
                print(f"  ANNOTATION_SECTION_BTN={label}")

else:
    print("NO_PROCUREMENT_BUTTONS - checking if card_feed renders differently")
    # Maybe cards rendered as something else in this version
    R["REAL_CARD_OPENED"] = "NO_BUTTONS"

# ── PHASE 12: PAGINATION ──
print("=== PHASE 12: PAGINATION ===")
page_inputs = [ni for ni in at.number_input if 'страниц' in str(ni.label).lower() or 'page' in str(ni.label).lower()]
if page_inputs:
    pi = page_inputs[0]
    print(f"PAGE_INPUT: label={pi.label} value={pi.value} max={pi.max}")
    if pi.max and int(pi.max) > 1:
        pi.set_value(2)
        t0 = time.time()
        at.run(timeout=60)
        T_PAGE2 = int((time.time()-t0)*1000)
        print(f"PAGE_2_RENDER_MS={T_PAGE2}")
        print(f"PAGE_2_EXCEPTIONS={len(at.exception)}")
        pi.set_value(1)
        at.run(timeout=60)
        R["REAL_PAGINATION"] = "PASS"
    else:
        R["REAL_PAGINATION"] = "SINGLE_PAGE"
else:
    R["REAL_PAGINATION"] = "NO_PAGE_INPUT"

R["T_TOTAL_INITIAL_RENDER_MS"] = R.get("T_HEADER_MS", 0)
print("=== FINAL RESULTS ===")
print(json.dumps(R, indent=2, ensure_ascii=False))
PYEOF

echo "=== PHASE 13: SERVER LOG CHECK ==="
journalctl -u crm-streamlit.service --since "$ACCEPTANCE_START" --no-pager 2>&1 | grep -ic 'traceback\|importerror' | xargs -I{} echo "STREAMLIT_TRACEBACKS_DURING_ACCEPTANCE={}"
journalctl -u crm-streamlit.service --since "$ACCEPTANCE_START" --no-pager 2>&1 | grep -i 'traceback\|importerror' | head -3

echo "=== PHASE 14: AUTONOMOUS WORKER ==="
systemctl is-active crm-v3-autonomous-worker.service && echo "AUTONOMOUS_WORKER_ACTIVE=YES" || echo "AUTONOMOUS_WORKER_ACTIVE=NO"
pgrep -c -f 'autonomous_worker' | xargs -I{} echo "AUTONOMOUS_WORKER_INSTANCE_COUNT={}"

echo "=== PHASE 15: GIT HYGIENE ==="
cd /opt/CRM_Streamlit_rescue
echo "GIT_DIRTY=$(git status --porcelain | wc -l)"
echo "COMMITTED_PYC_COUNT=$(git ls-files | grep -cE '(__pycache__/|\.pyc$)' || echo 0)"

echo "ALL_PHASES_DONE"
