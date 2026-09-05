#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path_tabs = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/tabs.py"
with open(path_tabs, "r", encoding="utf-8") as f:
    lines = f.readlines()

target_idx = None
for i, line in enumerate(lines):
    if 'filtered_total = sql_counts.get(selected_review' in line:
        target_idx = i
        break

assert target_idx is not None, "filtered_total line not found"

indent = "    "
replacement_lines = [
    f"{indent}from src.services.annotation_state_service import filter_workset_ids_sql\n",
    f"{indent}# ── SQL filter before pagination ──\n",
    f"{indent}filtered_workset_ids = filter_workset_ids_sql(workset_ids, selected_review, crm_db)\n",
    f"{indent}filtered_total = len(filtered_workset_ids)\n",
    f"{indent}page, offset = _page_offset(\"torgi\", filtered_total)\n",
    f"{indent}cards = _load_torgi(_PAGE_SIZE, offset, sort_mode, filtered_workset_ids)\n",
]

# Replace lines[target_idx-1:target_idx+3] (comment line + filtered_total line + page line + cards line)
lines[target_idx-1:target_idx+3] = replacement_lines

with open(path_tabs, "w", encoding="utf-8") as f:
    f.writelines(lines)
print("tabs.py torgi workset block patched by line index successfully")
PYEOF
