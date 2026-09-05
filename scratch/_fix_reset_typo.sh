#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path_tabs = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/tabs.py"
with open(path_tabs, "r", encoding="utf-8") as f:
    code_tabs = f.read()

target = 'st.session_state[f"{session_key}_workset_page"] = 1'
replacement = '_reset_torgi_page()'

assert target in code_tabs, f"target '{target}' not found in tabs.py"
code_tabs = code_tabs.replace(target, replacement)

with open(path_tabs, "w", encoding="utf-8") as f:
    f.write(code_tabs)

print("FIXED PAGE RESET TYPO IN tabs.py!")
PYEOF
