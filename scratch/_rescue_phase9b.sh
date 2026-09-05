#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== PHASE 9B: FIX CRLF AND PATCH TABS ==="

# First normalize line endings in tabs.py
sed -i 's/\r$//' src/ui/components/analytics_v2/tabs.py

# Now add _render_review_filter_from_counts helper function before _render_torgi_tab
# Find the line number of _render_torgi_tab
TORGI_LINE=$(grep -n 'def _render_torgi_tab' src/ui/components/analytics_v2/tabs.py | head -1 | cut -d: -f1)
echo "TORGI_TAB_LINE=$TORGI_LINE"

# Insert the helper function before _render_torgi_tab
cat > /tmp/_helper_fn.py << 'PYEOF'


def _render_review_filter_from_counts(
    counts: dict[str, int], session_key: str, *, on_change=None
) -> str:
    """Render review filter pills using pre-computed SQL counts."""
    from src.ui.components.analytics_v2.stage_workspace import FILTERS
    labels = [f"{label} · {counts.get(key, 0)}" for key, label in FILTERS]
    selected_label = st.pills(
        "Эксперт",
        labels,
        default=labels[0],
        key=f"annotation_state_filter_{session_key}",
        on_change=on_change,
    )
    return FILTERS[labels.index(selected_label)][0]
PYEOF

/opt/CRM_Streamlit/.venv313/bin/python << PYEOF
filepath = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/tabs.py"
with open(filepath, 'r') as f:
    content = f.read()

# Insert helper before _render_torgi_tab
helper = open('/tmp/_helper_fn.py').read()
old = 'def _render_torgi_tab'
idx = content.find(old)
if idx > 0:
    content = content[:idx] + helper + '\n\n' + content[idx:]
    print("HELPER_INSERTED=YES")
else:
    print("HELPER_INSERTED=NO")

with open(filepath, 'w') as f:
    f.write(content)
PYEOF

echo "--- Now patch the torgi workset loading ---"
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
filepath = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/tabs.py"
with open(filepath, 'r') as f:
    content = f.read()

old = """    workset_ids = _stage_workset_ids("torgi")
    sort_mode = st.radio(
        "Сортировка по сроку",
        list(DEADLINE_SORT_LABELS),
        format_func=lambda value: DEADLINE_SORT_LABELS[value],
        horizontal=True,
        key="torgi_deadline_sort",
        on_change=_reset_torgi_page,
    )
    from src.services.annotation_state_service import load_current_annotation_states
    from src.services.db_bootstrap import connect_databases
    _, _, crm_db, _ = connect_databases()
    annotation_states = load_current_annotation_states(workset_ids, crm_db)
    selected_review = render_review_filter(
        annotation_states, _SESSION_TORGI, on_change=_reset_torgi_page
    )
    selected_ids = filtered_review_ids(annotation_states, selected_review)
    page, offset = _page_offset("torgi", len(selected_ids))
    cards = _load_torgi(_PAGE_SIZE, offset, sort_mode, selected_ids)"""

new = """    workset_ids = _stage_workset_ids("torgi")
    sort_mode = st.radio(
        "Сортировка по сроку",
        list(DEADLINE_SORT_LABELS),
        format_func=lambda value: DEADLINE_SORT_LABELS[value],
        horizontal=True,
        key="torgi_deadline_sort",
        on_change=_reset_torgi_page,
    )
    from src.services.annotation_state_service import (
        count_annotation_states_sql,
        annotation_filter_sql_clause,
        load_current_annotation_states,
    )
    from src.services.db_bootstrap import connect_databases
    _, _, crm_db, _ = connect_databases()
    # ── SQL-level counts (no full Python workset load) ──
    sql_counts = count_annotation_states_sql(workset_ids, crm_db)
    selected_review = _render_review_filter_from_counts(
        sql_counts, _SESSION_TORGI, on_change=_reset_torgi_page
    )
    # ── Filtered count for pagination ──
    filtered_total = sql_counts.get(selected_review, sql_counts["ALL"])
    page, offset = _page_offset("torgi", filtered_total)
    cards = _load_torgi(_PAGE_SIZE, offset, sort_mode, workset_ids)
    # ── Page-only annotation state load (max 25 IDs) ──
    page_ids = [c["id"] for c in cards]
    annotation_states = load_current_annotation_states(page_ids, crm_db)"""

if old in content:
    content = content.replace(old, new)
    print("TORGI_PATCH=YES")
else:
    print("TORGI_PATCH=NO")
    # Try with slight variations
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'workset_ids = _stage_workset_ids("torgi")' in line:
            print(f"Found at line {i+1}: [{repr(line)}]")

with open(filepath, 'w') as f:
    f.write(content)
PYEOF

echo "PHASE_9B=DONE"
