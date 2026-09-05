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
    if "def _page_offset" in l:
        start_idx = i
    if start_idx is not None and "return int(page)" in l:
        end_idx = i + 1
        break

assert start_idx is not None and end_idx is not None

new_lines = [
    "def _page_offset(stage: str, total: int) -> tuple[int, int]:\n",
    "    pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)\n",
    '    key = f"{stage}_workset_page"\n',
    "    if key not in st.session_state:\n",
    "        st.session_state[key] = 1\n",
    "    elif st.session_state[key] > pages:\n",
    "        st.session_state[key] = pages\n",
    '    val = st.session_state.get(key, 1)\n',
    '    page = st.number_input("Страница", min_value=1, max_value=pages, value=val, key=key)\n',
    "    return int(page), (int(page) - 1) * _PAGE_SIZE\n",
]

lines[start_idx:end_idx] = new_lines

with open(path_tabs, "w", encoding="utf-8") as f:
    f.writelines(lines)

print("UPDATED _page_offset WITH EXPLICIT value=val IN tabs.py!")
PYEOF
