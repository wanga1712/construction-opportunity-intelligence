#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path_tabs = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/tabs.py"
with open(path_tabs, "r", encoding="utf-8") as f:
    code_tabs = f.read()

target_torgi = """    # ── Filtered count for pagination ──
    filtered_total = sql_counts.get(selected_review, sql_counts["ALL"])
    page, offset = _page_offset("torgi", filtered_total)
    cards = _load_torgi(_PAGE_SIZE, offset, sort_mode, workset_ids)"""

replacement_torgi = """    from src.services.annotation_state_service import filter_workset_ids_sql
    # ── SQL filter before pagination ──
    filtered_workset_ids = filter_workset_ids_sql(workset_ids, selected_review, crm_db)
    filtered_total = len(filtered_workset_ids)
    page, offset = _page_offset("torgi", filtered_total)
    cards = _load_torgi(_PAGE_SIZE, offset, sort_mode, filtered_workset_ids)"""

assert target_torgi in code_tabs, "target_torgi not found in tabs.py"
code_tabs = code_tabs.replace(target_torgi, replacement_torgi)

with open(path_tabs, "w", encoding="utf-8") as f:
    f.write(code_tabs)
print("tabs.py torgi workset block patched successfully")
PYEOF
