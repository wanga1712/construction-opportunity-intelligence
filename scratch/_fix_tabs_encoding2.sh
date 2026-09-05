#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path_tabs = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/tabs.py"
with open(path_tabs, "r", encoding="utf-8") as f:
    lines = f.readlines()

start_idx = None
end_idx = None
for i, l in enumerate(lines):
    if "def _render_review_filter_from_counts" in l:
        start_idx = i
    if start_idx is not None and "return FILTERS[labels.index(selected_label)][0]" in l:
        end_idx = i + 1
        break

print(f"start_idx={start_idx}, end_idx={end_idx}")
assert start_idx is not None and end_idx is not None

new_func_lines = [
    "def _render_review_filter_from_counts(\n",
    "    counts: dict[str, int], session_key: str, *, on_change=None\n",
    ") -> str:\n",
    '    """Render review filter pills using pre-computed SQL counts."""\n',
    "    from src.ui.components.analytics_v2.stage_workspace import FILTERS\n",
    '    labels = [f"{label} · {counts.get(key, 0)}" for key, label in FILTERS]\n',
    "    selected_label = st.pills(\n",
    '        "Экспертная разметка",\n',
    "        labels,\n",
    "        default=labels[0],\n",
    '        key=f"annotation_state_filter_{session_key}",\n',
    "        on_change=on_change,\n",
    "    )\n",
    "    return FILTERS[labels.index(selected_label)][0]\n",
]

lines[start_idx:end_idx] = new_func_lines

with open(path_tabs, "w", encoding="utf-8") as f:
    f.writelines(lines)

print("TABS.PY FUNCTION _render_review_filter_from_counts SUCCESSFULLY REPLACED!")
PYEOF
