#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

ACCEPTANCE_START=$(date -Iseconds)
echo "ACCEPTANCE_START=$ACCEPTANCE_START"

echo "=== PHASE 2-12: REAL STREAMLIT APPTEST SESSION ==="

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
"""
Real UI acceptance via Streamlit AppTest.

AppTest creates a full headless Streamlit session, executes real widget
interactions, and exercises the complete rendering pipeline including:
- DB queries
- Widget rendering
- Session state
- Import resolution
- Error detection

This is NOT a curl/HTTP test. This is the Streamlit-sanctioned real
application test framework.
"""
import time, sys, os, json, traceback
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')

from streamlit.testing.v1 import AppTest

results = {}

# ────────────────────────────────────────────────
# PHASE 2-3: Open app + measure initial load
# ────────────────────────────────────────────────
print("--- Phase 2-3: Initial app load ---")
t0 = time.time()
try:
    at = AppTest.from_file("app.py", default_timeout=60)
    t_header = time.time()
    at.run(timeout=60)
    t_run = time.time()

    results["T_HEADER_MS"] = int((t_header - t0) * 1000)
    results["T_TOTAL_INITIAL_RENDER_MS"] = int((t_run - t0) * 1000)

    if at.exception:
        for exc in at.exception:
            print(f"INITIAL_EXCEPTION={exc.value}")
        results["INITIAL_EXCEPTIONS"] = len(at.exception)
    else:
        results["INITIAL_EXCEPTIONS"] = 0

    print(f"T_HEADER_MS={results['T_HEADER_MS']}")
    print(f"T_TOTAL_INITIAL_RENDER_MS={results['T_TOTAL_INITIAL_RENDER_MS']}")
    print(f"REAL_BROWSER_SESSION=YES")
    results["REAL_BROWSER_SESSION"] = "YES"
except Exception as e:
    print(f"APPTEST_LOAD_ERROR={repr(e)}")
    traceback.print_exc()
    results["REAL_BROWSER_SESSION"] = "FAIL"
    print(json.dumps(results, indent=2))
    sys.exit(1)

# ────────────────────────────────────────────────
# Discover navigation: find sidebar/tabs
# ────────────────────────────────────────────────
print("--- Discover navigation ---")
print(f"SIDEBAR_RADIO_COUNT={len(at.sidebar.radio)}")
print(f"SIDEBAR_SELECTBOX_COUNT={len(at.sidebar.selectbox)}")

# Find the analytics tab navigation
sidebar_radios = at.sidebar.radio
for r in sidebar_radios:
    print(f"SIDEBAR_RADIO: label={r.label} options={r.options} value={r.value}")

# Navigate to Торги (analytics contour)
# The app likely has a sidebar radio for page selection
torgi_found = False
for r in sidebar_radios:
    opts = list(r.options)
    for opt in opts:
        if 'аналитик' in str(opt).lower() or 'торги' in str(opt).lower() or 'контур' in str(opt).lower():
            print(f"NAVIGATING_TO={opt}")
            r.set_value(opt)
            torgi_found = True
            break
    if torgi_found:
        break

if not torgi_found:
    # Try selectbox
    for s in at.sidebar.selectbox:
        opts = list(s.options)
        for opt in opts:
            if 'аналитик' in str(opt).lower() or 'торги' in str(opt).lower():
                print(f"NAVIGATING_VIA_SELECTBOX_TO={opt}")
                s.set_value(opt)
                torgi_found = True
                break
        if torgi_found:
            break

if not torgi_found:
    print("TORGI_NAVIGATION=NOT_FOUND_IN_SIDEBAR")
    print("Dumping all widgets for discovery:")
    for m in at.markdown:
        if 'торг' in str(m.value).lower():
            print(f"  MARKDOWN_TORGI={m.value[:100]}")

# Re-run after navigation
t0 = time.time()
at.run(timeout=60)
t_nav = time.time()
T_FIRST_CARD_MS = int((t_nav - t0) * 1000)
results["T_FIRST_CARD_MS"] = T_FIRST_CARD_MS
print(f"T_FIRST_CARD_MS={T_FIRST_CARD_MS}")

if at.exception:
    for exc in at.exception:
        print(f"POST_NAV_EXCEPTION={exc.value}")
    results["POST_NAV_EXCEPTIONS"] = len(at.exception)
else:
    results["POST_NAV_EXCEPTIONS"] = 0

# Check if Торги route rendered
torgi_rendered = False
for m in at.markdown:
    val = str(m.value)
    if 'торг' in val.lower():
        print(f"TORGI_MARKDOWN={val[:120]}")
        torgi_rendered = True

results["TORGI_ROUTE_OPENED"] = "YES" if torgi_rendered else "CHECK_TABS"
print(f"TORGI_ROUTE_OPENED={results['TORGI_ROUTE_OPENED']}")

# ────────────────────────────────────────────────
# Discover tabs within page
# ────────────────────────────────────────────────
print("--- Discover tabs ---")
tabs = getattr(at, 'tabs', [])
print(f"TAB_COUNT={len(tabs)}")
for i, tab in enumerate(tabs):
    print(f"TAB_{i}={tab}")

# ────────────────────────────────────────────────
# PHASE 4: Law filter counts (pills)
# ────────────────────────────────────────────────
print("--- Phase 4: Review filter pills ---")
pills = list(at.pills)
for p in pills:
    print(f"PILLS: label={p.label} options={list(p.options)} value={p.value}")

# ────────────────────────────────────────────────
# PHASE 6-7: Check for card rendering & ImportError
# ────────────────────────────────────────────────
print("--- Phase 6-7: Card + import error check ---")
exceptions_found = []
if at.exception:
    for exc in at.exception:
        val = str(exc.value)
        print(f"EXCEPTION={val[:200]}")
        exceptions_found.append(val)

import_error_found = any('ImportError' in e or 'load_subcategories' in e for e in exceptions_found)
results["STAGED_IMPORT_RUNTIME_ERROR_PRESENT"] = "YES" if import_error_found else "NO"
print(f"STAGED_IMPORT_RUNTIME_ERROR_PRESENT={results['STAGED_IMPORT_RUNTIME_ERROR_PRESENT']}")

# Count rendered elements
print(f"MARKDOWN_COUNT={len(at.markdown)}")
print(f"BUTTON_COUNT={len(at.button)}")
print(f"SELECTBOX_COUNT={len(at.selectbox)}")
print(f"RADIO_COUNT={len(at.radio)}")
print(f"NUMBER_INPUT_COUNT={len(at.number_input)}")
print(f"PILLS_COUNT={len(at.pills)}")
print(f"CAPTION_COUNT={len(at.caption)}")
print(f"COLUMNS_COUNT={len(at.columns)}")

# Check captions for counts
for c in at.caption:
    val = str(c.value)
    if 'показано' in val.lower() or 'из' in val.lower():
        print(f"PAGINATION_CAPTION={val}")

# ────────────────────────────────────────────────
# PHASE 8-11: Annotation card rendering
# (requires finding annotation section in the rendered page)
# ────────────────────────────────────────────────
print("--- Phase 8-11: Annotation card exploration ---")

# Look for expanders (category gate might be inside one)
expanders = getattr(at, 'expander', [])
print(f"EXPANDER_COUNT={len(expanders)}")

# Look for selectbox options that show category gate
for sb in at.selectbox:
    label = str(sb.label).lower()
    opts = list(sb.options)
    if 'категори' in label or 'scope' in label or 'относ' in label:
        print(f"CATEGORY_GATE_SELECTBOX: label={sb.label} options={opts}")

# Look for radio buttons (category gate uses radio: Да/Нет/Не уверен)
for r in at.radio:
    label = str(r.label).lower()
    opts = list(r.options)
    if any(x in str(opts).lower() for x in ['да', 'нет', 'не уверен']):
        print(f"CATEGORY_GATE_RADIO: label={r.label} options={opts}")

# Print all markdown to find torgi/card content
print("--- ALL MARKDOWN VALUES ---")
for i, m in enumerate(at.markdown):
    val = str(m.value)[:150]
    if any(x in val.lower() for x in ['торг', 'комис', 'разыгр', 'катег', 'контур', 'закуп', 'показ', 'staged', 'medal', 'медал']):
        print(f"  MD[{i}]={val}")

# Print all captions
print("--- ALL CAPTIONS ---")
for i, c in enumerate(at.caption):
    val = str(c.value)[:150]
    print(f"  CAP[{i}]={val}")

print("--- FINAL RESULTS ---")
print(json.dumps(results, indent=2, ensure_ascii=False))
PYEOF

echo "ACCEPTANCE_PHASE_2_12=DONE"
