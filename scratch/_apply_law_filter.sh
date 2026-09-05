#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys

# 1. Update src/services/annotation_state_service.py
path_ass = "/opt/CRM_Streamlit_rescue/src/services/annotation_state_service.py"
with open(path_ass, "r", encoding="utf-8") as f:
    code_ass = f.read()

law_funcs = """

LAW_FILTERS = (
    ("ALL", "\\u0412\\u0441\\u0435"),
    ("44-\\u0424\\u0417", "44-\\u0424\\u0417"),
    ("223-\\u0424\\u0417", "223-\\u0424\\u0417"),
)

def count_law_states_sql(procurement_ids: list[int], crm_db: Any) -> dict[str, int]:
    \"\"\"Compute law filter counts via SQL aggregation.\"\"\"
    if not procurement_ids:
        return {"ALL": 0, "44-\\u0424\\u0417": 0, "223-\\u0424\\u0417": 0}
    rows = crm_db.execute_query(
        "SELECT source_table, count(*) AS cnt FROM crm_procurements WHERE id = ANY(%s) GROUP BY source_table",
        (procurement_ids,),
    )
    c44 = 0
    c223 = 0
    for r in (rows or []):
        stbl = r.get("source_table")
        cnt = int(r.get("cnt") or 0)
        if stbl == "reestr_contract_44_fz":
            c44 = cnt
        elif stbl == "reestr_contract_223_fz":
            c223 = cnt
    return {
        "ALL": len(procurement_ids),
        "44-\\u0424\\u0417": c44,
        "223-\\u0424\\u0417": c223,
    }

def filter_workset_ids_by_law(procurement_ids: list[int], selected_law: str, crm_db: Any) -> list[int]:
    \"\"\"Filter procurement_ids by law in SQL before review filtering and pagination.\"\"\"
    if not procurement_ids or selected_law == "ALL":
        return procurement_ids
    if selected_law == "44-\\u0424\\u0417":
        source_tbl = "reestr_contract_44_fz"
    elif selected_law == "223-\\u0424\\u0417":
        source_tbl = "reestr_contract_223_fz"
    else:
        return procurement_ids
        
    rows = crm_db.execute_query(
        "SELECT id FROM crm_procurements WHERE id = ANY(%s) AND source_table = %s",
        (procurement_ids, source_tbl),
    )
    matching = set(r["id"] for r in (rows or []))
    return [pid for pid in procurement_ids if pid in matching]
"""

if "def count_law_states_sql" not in code_ass:
    code_ass += law_funcs
    with open(path_ass, "w", encoding="utf-8") as f:
        f.write(code_ass)
    print("Added law functions to annotation_state_service.py")
else:
    print("Law functions already present in annotation_state_service.py")

# 2. Update src/ui/components/analytics_v2/tabs.py
path_tabs = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/tabs.py"
with open(path_tabs, "r", encoding="utf-8") as f:
    lines = f.readlines()

# Add _render_law_filter_from_counts before _render_review_filter_from_counts
review_filter_line_idx = None
for i, l in enumerate(lines):
    if "def _render_review_filter_from_counts" in l:
        review_filter_line_idx = i
        break

assert review_filter_line_idx is not None, "def _render_review_filter_from_counts not found"

law_render_func_lines = [
    "def _render_law_filter_from_counts(\n",
    "    counts: dict[str, int], session_key: str, *, on_change=None\n",
    ") -> str:\n",
    '    """Render law filter pills using pre-computed SQL counts."""\n',
    "    from src.services.annotation_state_service import LAW_FILTERS\n",
    '    labels = [f"{label} \\u00b7 {counts.get(key, 0)}" for key, label in LAW_FILTERS]\n',
    "    selected_label = st.pills(\n",
    '        "\\u0417\\u0430\\u043a\\u043e\\u043d / \\u0438\\u0441\\u0442\\u043e\\u0447\\u043d\\u0438\\u043a",\n',
    "        labels,\n",
    "        default=labels[0],\n",
    '        key=f"torgi_law_filter_{session_key}",\n',
    "        on_change=on_change,\n",
    "    )\n",
    "    return LAW_FILTERS[labels.index(selected_label)][0]\n\n\n",
]

if "def _render_law_filter_from_counts" not in "".join(lines):
    lines[review_filter_line_idx:review_filter_line_idx] = law_render_func_lines
    print("Inserted _render_law_filter_from_counts in tabs.py")

# Update _render_torgi_tab to include law filter pipeline
torgi_sql_counts_idx = None
for i, l in enumerate(lines):
    if "sql_counts = count_annotation_states_sql" in l:
        torgi_sql_counts_idx = i
        break

assert torgi_sql_counts_idx is not None, "count_annotation_states_sql line not found in _render_torgi_tab"

# Replace lines around sql_counts with law filter + review filter pipeline
# Find start of block: line with `from src.services.annotation_state_service import (` or `sql_counts =`
block_start_idx = torgi_sql_counts_idx
while block_start_idx > 0 and "from src.services.annotation_state_service" not in lines[block_start_idx]:
    block_start_idx -= 1

cards_line_idx = torgi_sql_counts_idx
while cards_line_idx < len(lines) and "cards = _load_torgi" not in lines[cards_line_idx]:
    cards_line_idx += 1

assert cards_line_idx < len(lines), "cards = _load_torgi line not found"

indent = "    "
torgi_pipeline_lines = [
    f"{indent}from src.services.annotation_state_service import (\n",
    f"{indent}    count_annotation_states_sql,\n",
    f"{indent}    count_law_states_sql,\n",
    f"{indent}    filter_workset_ids_by_law,\n",
    f"{indent}    filter_workset_ids_sql,\n",
    f"{indent}    load_current_annotation_states,\n",
    f"{indent})\n",
    f"{indent}from src.services.db_bootstrap import connect_databases\n",
    f"{indent}_, _, crm_db, _ = connect_databases()\n",
    f"{indent}# ── Law filter (SQL count & filter) ──\n",
    f"{indent}law_counts = count_law_states_sql(workset_ids, crm_db)\n",
    f"{indent}selected_law = _render_law_filter_from_counts(\n",
    f"{indent}    law_counts, _SESSION_TORGI, on_change=_reset_torgi_page\n",
    f"{indent})\n",
    f"{indent}law_workset_ids = filter_workset_ids_by_law(workset_ids, selected_law, crm_db)\n",
    f"{indent}# ── Expert review filter (SQL count & filter) ──\n",
    f"{indent}sql_counts = count_annotation_states_sql(law_workset_ids, crm_db)\n",
    f"{indent}selected_review = _render_review_filter_from_counts(\n",
    f"{indent}    sql_counts, _SESSION_TORGI, on_change=_reset_torgi_page\n",
    f"{indent})\n",
    f"{indent}filtered_workset_ids = filter_workset_ids_sql(law_workset_ids, selected_review, crm_db)\n",
    f"{indent}filtered_total = len(filtered_workset_ids)\n",
    f"{indent}page, offset = _page_offset(\"torgi\", filtered_total)\n",
    f"{indent}cards = _load_torgi(_PAGE_SIZE, offset, sort_mode, filtered_workset_ids)\n",
]

lines[block_start_idx:cards_line_idx+1] = torgi_pipeline_lines

with open(path_tabs, "w", encoding="utf-8") as f:
    f.writelines(lines)

print("Updated _render_torgi_tab in tabs.py with complete Law + Review filter pipeline!")

PYEOF
