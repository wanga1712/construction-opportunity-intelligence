#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, re

# Patch tabs.py
path_tabs = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/tabs.py"
with open(path_tabs, "r", encoding="utf-8") as f:
    code_tabs = f.read()

# Replace corrupted labels line in _render_review_filter_from_counts
code_tabs = re.sub(
    r'labels = \[f"{label} \?\? \{counts\.get\(key, 0\)\}" for key, label in FILTERS\]',
    'labels = [f"{label} · {counts.get(key, 0)}" for key, label in FILTERS]',
    code_tabs
)

code_tabs = re.sub(
    r'st\.pills\(\s*"\?+"\s*,',
    'st.pills(\n        "Экспертная разметка",',
    code_tabs
)

# Update torgi workset loading to use filter_workset_ids_sql
old_torgi_pattern = r'sql_counts = count_annotation_states_sql\(workset_ids, crm_db\)\s+selected_review = _render_review_filter_from_counts\(\s+sql_counts, _SESSION_TORGI, on_change=_reset_torgi_page\s+\)\s+# ── Filtered count for pagination ──\s+filtered_total = sql_counts\.get\(selected_review, sql_counts\["ALL"\]\)\s+page, offset = _page_offset\("torgi", filtered_total\)\s+cards = _load_torgi\(_PAGE_SIZE, offset, sort_mode, workset_ids\)'

new_torgi_code = """from src.services.annotation_state_service import filter_workset_ids_sql
    sql_counts = count_annotation_states_sql(workset_ids, crm_db)
    selected_review = _render_review_filter_from_counts(
        sql_counts, _SESSION_TORGI, on_change=_reset_torgi_page
    )
    # ── SQL filter before pagination ──
    filtered_workset_ids = filter_workset_ids_sql(workset_ids, selected_review, crm_db)
    filtered_total = len(filtered_workset_ids)
    page, offset = _page_offset("torgi", filtered_total)
    cards = _load_torgi(_PAGE_SIZE, offset, sort_mode, filtered_workset_ids)"""

code_tabs = re.sub(old_torgi_pattern, new_torgi_code, code_tabs)

with open(path_tabs, "w", encoding="utf-8") as f:
    f.write(code_tabs)
print("tabs.py patched successfully")

# Patch stage_workspace.py
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
