#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path_tabs = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/tabs.py"
with open(path_tabs, "r", encoding="utf-8") as f:
    code = f.read()

# Replace _render_review_filter_from_counts function entirely
import re

old_func_pattern = r'def _render_review_filter_from_counts\(.*?\nreturn FILTERS\[labels\.index\(selected_label\)\]\[0\]'

new_func = """def _render_review_filter_from_counts(
    counts: dict[str, int], session_key: str, *, on_change=None
) -> str:
    \"\"\"Render review filter pills using pre-computed SQL counts.\"\"\"
    from src.ui.components.analytics_v2.stage_workspace import FILTERS
    labels = [f"{label} · {counts.get(key, 0)}" for key, label in FILTERS]
    selected_label = st.pills(
        "Экспертная разметка",
        labels,
        default=labels[0],
        key=f"annotation_state_filter_{session_key}",
        on_change=on_change,
    )
    return FILTERS[labels.index(selected_label)][0]"""

match = re.search(old_func_pattern, code, flags=re.DOTALL)
assert match is not None, "old_func_pattern not found"

code = code[:match.start()] + new_func + code[match.end():]

with open(path_tabs, "w", encoding="utf-8") as f:
    f.write(code)

print("SUCCESSFULLY REPLACED _render_review_filter_from_counts IN tabs.py!")
PYEOF
