#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path_tabs = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/tabs.py"
with open(path_tabs, "r", encoding="utf-8") as f:
    lines = f.readlines()

# 1. Update _page_offset signature & implementation
start_idx = None
end_idx = None
for i, l in enumerate(lines):
    if "def _page_offset" in l:
        start_idx = i
    if start_idx is not None and "return int(page)" in l:
        end_idx = i + 1
        break

assert start_idx is not None and end_idx is not None

new_page_offset_lines = [
    "def _page_offset(stage: str, total: int, law_key: str = \"ALL\") -> tuple[int, int]:\n",
    "    pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)\n",
    "    key = f\"{stage}_workset_page_{law_key}\"\n",
    "    page = st.number_input(\"\\u0421\\u0442\\u0440\\u0430\\u043d\\u0438\\u0446\\u0430\", 1, pages, 1, key=key)\n",
    "    return int(page), (int(page) - 1) * _PAGE_SIZE\n",
]

lines[start_idx:end_idx] = new_page_offset_lines

# 2. Update call in _render_torgi_tab
for i, l in enumerate(lines):
    if "page, offset = _page_offset(\"torgi\", filtered_total)" in l:
        lines[i] = "    page, offset = _page_offset(\"torgi\", filtered_total, selected_law)\n"
        break

with open(path_tabs, "w", encoding="utf-8") as f:
    f.writelines(lines)

print("SUCCESSFULLY APPLIED DYNAMIC LAW KEY TO _page_offset IN tabs.py!")
PYEOF
