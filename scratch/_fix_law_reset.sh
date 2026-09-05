#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path_tabs = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/tabs.py"
with open(path_tabs, "r", encoding="utf-8") as f:
    code_tabs = f.read()

target_law_func = """def _render_law_filter_from_counts(
    counts: dict[str, int], session_key: str, *, on_change=None
) -> str:
    \"\"\"Render law filter pills using pre-computed SQL counts.\"\"\"
    from src.services.annotation_state_service import LAW_FILTERS
    labels = [f"{label} \\u00b7 {counts.get(key, 0)}" for key, label in LAW_FILTERS]
    selected_label = st.pills(
        "\\u0417\\u0430\\u043a\\u043e\\u043d / \\u0438\\u0441\\u0442\\u043e\\u0447\\u043d\\u0438\\u043a",
        labels,
        default=labels[0],
        key=f"torgi_law_filter_{session_key}",
        on_change=on_change,
    )
    return LAW_FILTERS[labels.index(selected_label)][0]"""

replacement_law_func = """def _render_law_filter_from_counts(
    counts: dict[str, int], session_key: str, *, on_change=None
) -> str:
    \"\"\"Render law filter pills using pre-computed SQL counts.\"\"\"
    from src.services.annotation_state_service import LAW_FILTERS
    labels = [f"{label} \\u00b7 {counts.get(key, 0)}" for key, label in LAW_FILTERS]
    key = f"torgi_law_filter_{session_key}"
    prev_key = f"prev_{key}"
    selected_label = st.pills(
        "\\u0417\\u0430\\u043a\\u043e\\u043d / \\u0438\\u0441\\u0442\\u043e\\u0447\\u043d\\u0438\\u043a",
        labels,
        default=labels[0],
        key=key,
        on_change=on_change,
    )
    if st.session_state.get(prev_key) != selected_label:
        st.session_state[prev_key] = selected_label
        st.session_state[f"{session_key}_workset_page"] = 1
    return LAW_FILTERS[labels.index(selected_label)][0]"""

assert target_law_func in code_tabs, "target_law_func not found"
code_tabs = code_tabs.replace(target_law_func, replacement_law_func)

with open(path_tabs, "w", encoding="utf-8") as f:
    f.write(code_tabs)

print("UPDATED _render_law_filter_from_counts WITH EXPLICIT STATE RESET ON CHANGE!")
PYEOF
