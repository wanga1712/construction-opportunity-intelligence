#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== PHASE 9C: LINE-BASED PATCH ==="

/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
filepath = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/tabs.py"
with open(filepath, 'r') as f:
    lines = f.readlines()

# Find the exact lines to replace
start_idx = None
end_idx = None
for i, line in enumerate(lines):
    if 'workset_ids = _stage_workset_ids("torgi")' in line and start_idx is None:
        start_idx = i
    if start_idx and 'cards = _load_torgi(_PAGE_SIZE, offset, sort_mode, selected_ids)' in line:
        end_idx = i
        break

if start_idx is None or end_idx is None:
    # Try alternate ending
    for i, line in enumerate(lines):
        if start_idx and 'cards = _load_torgi(' in line and i > start_idx:
            end_idx = i
            break

print(f"REPLACE_RANGE=lines {start_idx+1} to {end_idx+1}")
print(f"OLD_START=[{lines[start_idx].rstrip()}]")
print(f"OLD_END=[{lines[end_idx].rstrip()}]")

# Build replacement lines
indent = "    "  # 4 spaces
replacement = [
    f'{indent}workset_ids = _stage_workset_ids("torgi")\n',
    f'{indent}sort_mode = st.radio(\n',
    f'{indent}    "\u0421\u043e\u0440\u0442\u0438\u0440\u043e\u0432\u043a\u0430 \u043f\u043e \u0441\u0440\u043e\u043a\u0443",\n',
    f'{indent}    list(DEADLINE_SORT_LABELS),\n',
    f'{indent}    format_func=lambda value: DEADLINE_SORT_LABELS[value],\n',
    f'{indent}    horizontal=True,\n',
    f'{indent}    key="torgi_deadline_sort",\n',
    f'{indent}    on_change=_reset_torgi_page,\n',
    f'{indent})\n',
    f'{indent}from src.services.annotation_state_service import (\n',
    f'{indent}    count_annotation_states_sql,\n',
    f'{indent}    load_current_annotation_states,\n',
    f'{indent})\n',
    f'{indent}from src.services.db_bootstrap import connect_databases\n',
    f'{indent}_, _, crm_db, _ = connect_databases()\n',
    f'{indent}# \u2500\u2500 SQL-level counts (no full Python workset load) \u2500\u2500\n',
    f'{indent}sql_counts = count_annotation_states_sql(workset_ids, crm_db)\n',
    f'{indent}selected_review = _render_review_filter_from_counts(\n',
    f'{indent}    sql_counts, _SESSION_TORGI, on_change=_reset_torgi_page\n',
    f'{indent})\n',
    f'{indent}# \u2500\u2500 Filtered count for pagination \u2500\u2500\n',
    f'{indent}filtered_total = sql_counts.get(selected_review, sql_counts["ALL"])\n',
    f'{indent}page, offset = _page_offset("torgi", filtered_total)\n',
    f'{indent}cards = _load_torgi(_PAGE_SIZE, offset, sort_mode, workset_ids)\n',
    f'{indent}# \u2500\u2500 Page-only annotation state load (max 25 IDs) \u2500\u2500\n',
    f'{indent}page_ids = [c["id"] for c in cards]\n',
    f'{indent}annotation_states = load_current_annotation_states(page_ids, crm_db)\n',
]

lines[start_idx:end_idx+1] = replacement
with open(filepath, 'w') as f:
    f.writelines(lines)
print("TORGI_PATCH=YES")

# Verify
with open(filepath, 'r') as f:
    content = f.read()
assert 'count_annotation_states_sql' in content, "SQL counts not found"
assert 'page_ids = [c["id"] for c in cards]' in content, "page_ids not found"
print("VERIFICATION=PASS")
PYEOF

echo "--- Also patch komissia and razygranye tabs similarly ---"
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
filepath = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/tabs.py"
with open(filepath, 'r') as f:
    content = f.read()

# Komissia: find full-workset annotation load
# Check if komissia also does full load
import re
komissia_match = re.search(r'def _render_komissia_tab.*?(?=\ndef )', content, re.DOTALL)
if komissia_match:
    komissia = komissia_match.group()
    if 'load_current_annotation_states(workset_ids' in komissia:
        print("KOMISSIA_HAS_FULL_LOAD=YES (needs patch)")
    else:
        print("KOMISSIA_HAS_FULL_LOAD=NO")

razygranye_match = re.search(r'def _render_razygranye_tab.*?(?=\ndef )', content, re.DOTALL)
if razygranye_match:
    razygranye = razygranye_match.group()
    if 'load_current_annotation_states(workset_ids' in razygranye:
        print("RAZYGRANYE_HAS_FULL_LOAD=YES (needs patch)")
    else:
        print("RAZYGRANYE_HAS_FULL_LOAD=NO")
PYEOF

echo "PHASE_9C=DONE"
