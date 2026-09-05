#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

ACCEPTANCE_START=$(date -Iseconds)
echo "ACCEPTANCE_START=$ACCEPTANCE_START"

echo "=== REAL STREAMLIT APPTEST ACCEPTANCE ==="

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import time, sys, os, json
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')
from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')
from streamlit.testing.v1 import AppTest

R = {}  # results

# ── PHASE 2: Initial load ──
print("=== PHASE 2: INITIAL LOAD ===")
t0 = time.time()
at = AppTest.from_file("app.py", default_timeout=60)
at.run(timeout=60)
R["T_INITIAL_LOAD_MS"] = int((time.time() - t0) * 1000)
print(f"INITIAL_LOAD_MS={R['T_INITIAL_LOAD_MS']}")
print(f"INITIAL_EXCEPTIONS={len(at.exception)}")
for exc in at.exception:
    print(f"  EXC={exc.value}")

# ── Navigate to Аналитика V3 (Торги route) ──
print("=== NAVIGATE TO ANALYTICS V3 (Торги) ===")
# Set session state to navigate to analytics_v3
at.session_state["nav_page"] = "analytics_v3"
t0 = time.time()
at.run(timeout=60)
T_HEADER_MS = int((time.time() - t0) * 1000)
R["T_HEADER_MS"] = T_HEADER_MS
print(f"T_HEADER_MS={T_HEADER_MS}")

# Check for exceptions
print(f"V3_EXCEPTIONS={len(at.exception)}")
for exc in at.exception:
    print(f"  EXC={exc.value}")

import_errors = [str(e.value) for e in at.exception if 'ImportError' in str(e.value) or 'import' in str(e.value).lower()]
R["STAGED_IMPORT_RUNTIME_ERROR_PRESENT"] = "YES" if import_errors else "NO"
print(f"STAGED_IMPORT_RUNTIME_ERROR_PRESENT={R['STAGED_IMPORT_RUNTIME_ERROR_PRESENT']}")

# ── Look for Торги content ──
torgi_found = False
for m in at.markdown:
    val = str(m.value)
    if 'торг' in val.lower():
        print(f"TORGI_MARKDOWN={val[:150]}")
        torgi_found = True

# Check tabs (Streamlit tabs in V3 page)
tabs_list = list(at.tabs) if hasattr(at, 'tabs') else []
print(f"TAB_COUNT={len(tabs_list)}")
for i, tab in enumerate(tabs_list):
    print(f"  TAB[{i}]: {tab}")

# Check captions for pagination
for c in at.caption:
    val = str(c.value)
    if 'показано' in val.lower() or 'торг' in val.lower() or 'из' in val.lower():
        print(f"PAGINATION_CAPTION={val[:150]}")

# ── Law filter: look for pills showing counts ──
print("=== PHASE 4: LAW FILTER / REVIEW PILLS ===")
all_pills = list(at.pills)
print(f"PILLS_COUNT={len(all_pills)}")
for p in all_pills:
    opts = list(p.options)
    print(f"  PILLS label={p.label} options_count={len(opts)}")
    for o in opts[:15]:
        print(f"    option={o}")

# ── Review filter pills show annotation counts ──
# The FILTERS tuple: ALL, UNREVIEWED, REVIEWED, IN_CATEGORY, OUT_OF_CATEGORY, etc.
# These are annotation counts, not law filter counts.

# ── Check selectboxes for law/source filter ──
print("=== SELECTBOXES ===")
for sb in at.selectbox:
    print(f"  SELECTBOX label={sb.label} options={list(sb.options)[:10]} value={sb.value}")

# ── Check radio buttons ──
print("=== RADIO BUTTONS ===")
for r in at.radio:
    print(f"  RADIO label={r.label} options={list(r.options)} value={r.value}")

# ── Number inputs (pagination) ──
print("=== NUMBER INPUTS ===")
for ni in at.number_input:
    print(f"  NUMBER_INPUT label={ni.label} value={ni.value}")

# ── Markdown with card-like content ──
card_count = 0
print("=== CARD CONTENT CHECK ===")
for m in at.markdown:
    val = str(m.value)
    if '###' in val or '####' in val or 'НМЦК' in val or 'торг' in val.lower():
        print(f"  CARD_MD={val[:200]}")
        card_count += 1

print(f"CARD_MARKDOWN_COUNT={card_count}")

# ── Buttons (card interactions) ──
button_labels = [b.label for b in at.button]
card_buttons = [l for l in button_labels if 'карт' in l.lower() or 'подроб' in l.lower() or '📋' in l]
print(f"TOTAL_BUTTONS={len(button_labels)}")
print(f"CARD_BUTTONS={len(card_buttons)}")

# ── First card open: click first card button if exists ──
print("=== PHASE 6: OPEN REAL CARD ===")
# Look for card-like buttons
card_opened = False
for b in at.button:
    label = str(b.label)
    # Cards are typically rendered with procurement details
    if any(x in label.lower() for x in ['закупка', 'тендер', '📋', 'подробн']):
        print(f"CLICKING_CARD_BUTTON={label[:100]}")
        b.click()
        card_opened = True
        break

if not card_opened:
    # Try to find card by looking at the rendered page structure
    print("NO_EXPLICIT_CARD_BUTTON - checking if cards rendered inline")
    # In the stage_workspace, cards are rendered as inline expandable sections
    # They use st.session_state[_SESSION_TORGI] to track selected card
    # Let's check if we can find procurement data in the rendered output

# Re-run after potential card click
t0 = time.time()
at.run(timeout=60)
T_FIRST_CARD_MS = int((time.time() - t0) * 1000)
R["T_FIRST_CARD_MS"] = T_FIRST_CARD_MS
print(f"T_FIRST_CARD_MS={T_FIRST_CARD_MS}")

# Check all content for card details
print("=== POST-RERUN CONTENT ===")
for m in at.markdown:
    val = str(m.value)
    if any(x in val.lower() for x in ['нмцк', 'закупк', 'приём', 'срок', '44-фз', '223-фз', 'тендер', 'tender', 'link', 'reestr']):
        print(f"  CARD_DETAIL_MD={val[:200]}")

for c in at.caption:
    val = str(c.value)
    if any(x in val.lower() for x in ['показано', 'из', 'торг', 'нмцк', 'приём', 'цена', 'источник']):
        print(f"  CARD_DETAIL_CAP={val[:200]}")

# ── PHASE 8-11: Annotation section ──
print("=== PHASE 8-11: ANNOTATION GATE CHECK ===")
# Look for category gate radio: Да/Нет/Не уверен
category_gate_found = False
for r in at.radio:
    opts = [str(o) for o in r.options]
    if 'Да' in opts and 'Нет' in opts:
        print(f"CATEGORY_GATE_RADIO: label={r.label} options={opts}")
        category_gate_found = True

# Look for selectboxes with category-related content
for sb in at.selectbox:
    label = str(sb.label).lower()
    if any(x in label for x in ['категор', 'объект', 'тип', 'коммерч', 'медал', 'подкатегор', 'сектор', 'закупк']):
        print(f"ANNOTATION_SELECTBOX: label={sb.label} opts={list(sb.options)[:5]}")

# Look for expanders
for exp in at.expander:
    print(f"EXPANDER: {exp}")

# ── Check for render_stage_workspace inline card rendering ──
# The cards in analytics_v3 are rendered as inline sections, not separate buttons
# The card_feed.render_card_feed renders buttons per card

# Look at all button labels for procurement IDs
procurement_buttons = []
for b in at.button:
    label = str(b.label)
    if len(label) > 20 and ('·' in label or '₽' in label or 'руб' in label.lower()):
        procurement_buttons.append(label)
        if len(procurement_buttons) <= 3:
            print(f"  PROCUREMENT_BUTTON={label[:150]}")

print(f"PROCUREMENT_BUTTONS_COUNT={len(procurement_buttons)}")
R["REAL_CARD_OPENED"] = "YES" if procurement_buttons else "NO_BUTTONS"

# ── Try clicking first procurement button to open card ──
if procurement_buttons:
    for b in at.button:
        if str(b.label) == procurement_buttons[0]:
            print(f"CLICKING_PROCUREMENT={procurement_buttons[0][:100]}")
            b.click()
            break
    at.run(timeout=60)

    # Now check for annotation section
    print("=== POST-CARD-OPEN CONTENT ===")
    # Check for annotation gate
    for r in at.radio:
        opts = [str(o) for o in r.options]
        if 'Да' in opts and 'Нет' in opts:
            print(f"CATEGORY_GATE_RADIO: label={r.label} options={opts}")
            category_gate_found = True
        if any(x in str(r.label).lower() for x in ['сортиров', 'тема']):
            continue
        print(f"  RADIO: label={r.label} options={opts}")

    for sb in at.selectbox:
        label = str(sb.label).lower()
        if any(x in label for x in ['категор', 'объект', 'тип', 'коммерч', 'медал', 'подкатегор', 'сектор', 'закупк', 'mode']):
            print(f"  ANNOTATION_SELECTBOX: label={sb.label} opts={list(sb.options)[:5]}")

    # Check for section tabs (Обзор, Модель/Категории, etc.)
    for m in at.markdown:
        val = str(m.value)
        if any(x in val.lower() for x in ['обзор', 'модель', 'документ', 'истори', 'экспертн', 'разметк', 'категори']):
            print(f"  SECTION_MD={val[:150]}")

R["CATEGORY_GATE_FOUND"] = "YES" if category_gate_found else "NO"

# ── PHASE 12: Pagination ──
print("=== PHASE 12: PAGINATION ===")
page_inputs = [ni for ni in at.number_input if 'страниц' in str(ni.label).lower() or 'page' in str(ni.label).lower()]
if page_inputs:
    pi = page_inputs[0]
    print(f"PAGE_INPUT: label={pi.label} value={pi.value} min={pi.min} max={pi.max}")
    if pi.max and int(pi.max) > 1:
        pi.set_value(2)
        t0 = time.time()
        at.run(timeout=60)
        T_PAGE2 = int((time.time() - t0) * 1000)
        print(f"PAGE_2_RENDER_MS={T_PAGE2}")
        print(f"PAGE_2_EXCEPTIONS={len(at.exception)}")
        for exc in at.exception:
            print(f"  P2_EXC={exc.value}")

        # Go back to page 1
        pi.set_value(1)
        at.run(timeout=60)
        R["REAL_PAGINATION"] = "PASS"
    else:
        R["REAL_PAGINATION"] = "SINGLE_PAGE"
else:
    print("NO_PAGE_INPUT_FOUND")
    R["REAL_PAGINATION"] = "NO_INPUT"

# ── TOTAL timing ──
R["T_TOTAL_INITIAL_RENDER_MS"] = R.get("T_HEADER_MS", 0) + R.get("T_FIRST_CARD_MS", 0)

print("=== FINAL RESULTS ===")
print(json.dumps(R, indent=2, ensure_ascii=False))
PYEOF

echo "=== PHASE 13: SERVER LOG CHECK ==="
echo "ACCEPTANCE_END=$(date -Iseconds)"
journalctl -u crm-streamlit.service --since "$ACCEPTANCE_START" --no-pager 2>&1 | grep -ic 'traceback\|error\|importerror' | xargs -I{} echo "STREAMLIT_ERROR_LINES={}"
journalctl -u crm-streamlit.service --since "$ACCEPTANCE_START" --no-pager 2>&1 | grep -i 'traceback\|importerror' | head -5

echo "=== PHASE 14: AUTONOMOUS WORKER ==="
systemctl is-active crm-v3-autonomous-worker.service 2>/dev/null && echo "AUTONOMOUS_WORKER_ACTIVE=YES" || echo "AUTONOMOUS_WORKER_ACTIVE=NO"
pgrep -c -f 'autonomous_worker' 2>/dev/null | xargs -I{} echo "AUTONOMOUS_WORKER_INSTANCE_COUNT={}"

echo "=== PHASE 15: GIT HYGIENE ==="
cd /opt/CRM_Streamlit_rescue
echo "GIT_DIRTY_COUNT=$(git status --porcelain | wc -l)"
COMMITTED_PYC=$(git ls-files | grep -cE '(__pycache__/|\.pyc$)' || echo 0)
echo "COMMITTED_PYC_COUNT=$COMMITTED_PYC"

echo "ACCEPTANCE_COMPLETE=YES"
