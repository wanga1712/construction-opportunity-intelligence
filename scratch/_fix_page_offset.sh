#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path_tabs = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/tabs.py"
with open(path_tabs, "r", encoding="utf-8") as f:
    code_tabs = f.read()

target = """def _page_offset(stage: str, total: int) -> tuple[int, int]:
    pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = st.number_input("Страница", 1, pages, 1, key=f"{stage}_workset_page")
    return int(page), (int(page) - 1) * _PAGE_SIZE"""

replacement = """def _page_offset(stage: str, total: int) -> tuple[int, int]:
    pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    key = f"{stage}_workset_page"
    if key not in st.session_state:
        st.session_state[key] = 1
    elif st.session_state[key] > pages:
        st.session_state[key] = pages
    page = st.number_input("Страница", min_value=1, max_value=pages, key=key)
    return int(page), (int(page) - 1) * _PAGE_SIZE"""

assert target in code_tabs, "target _page_offset not found in tabs.py"
code_tabs = code_tabs.replace(target, replacement)

with open(path_tabs, "w", encoding="utf-8") as f:
    f.write(code_tabs)

print("UPDATED _page_offset IN tabs.py TO BIND DIRECTLY TO SESSION STATE!")
PYEOF
