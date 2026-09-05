#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path_tabs = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/tabs.py"
with open(path_tabs, "r", encoding="utf-8") as f:
    code_tabs = f.read()

# Replace corrupted labels line
target_line1 = '    labels = [f"{label} ?? {counts.get(key, 0)}" for key, label in FILTERS]'
replacement_line1 = '    labels = [f"{label} · {counts.get(key, 0)}" for key, label in FILTERS]'
if target_line1 in code_tabs:
    code_tabs = code_tabs.replace(target_line1, replacement_line1)
    print("Patched labels line")
else:
    print("target_line1 not found")

# Replace corrupted pills title
lines = code_tabs.splitlines()
for i, line in enumerate(lines):
    if 'st.pills(' in line and i+1 < len(lines) and '????????' in lines[i+1]:
        lines[i+1] = '        "Экспертная разметка",'
        print("Patched pills title")
code_tabs = "\n".join(lines)

# Replace torgi workset pagination/load logic
old_block = """    # ── Filtered count for pagination ──
    filtered_total = sql_counts.get(selected_review, sql_counts["ALL"])
    page, offset = _page_offset("torgi", filtered_total)
    cards = _load_torgi(_PAGE_SIZE, offset, sort_mode, workset_ids)"""

new_block = """    from src.services.annotation_state_service import filter_workset_ids_sql
    # ── SQL filter before pagination ──
    filtered_workset_ids = filter_workset_ids_sql(workset_ids, selected_review, crm_db)
    filtered_total = len(filtered_workset_ids)
    page, offset = _page_offset("torgi", filtered_total)
    cards = _load_torgi(_PAGE_SIZE, offset, sort_mode, filtered_workset_ids)"""

if old_block in code_tabs:
    code_tabs = code_tabs.replace(old_block, new_block)
    print("Patched torgi workset block")
else:
    print("old_block not found in tabs.py")

with open(path_tabs, "w", encoding="utf-8") as f:
    f.write(code_tabs)

path_sw = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/stage_workspace.py"
with open(path_sw, "r", encoding="utf-8") as f:
    code_sw = f.read()

code_sw = code_sw.replace(
    '(OUT_OF_CATEGORY, "Вне категорий"),',
    '(OUT_OF_CATEGORY, "Вне товарных категорий"),'
)

with open(path_sw, "w", encoding="utf-8") as f:
    f.write(code_sw)
print("stage_workspace.py patched successfully")

PYEOF
