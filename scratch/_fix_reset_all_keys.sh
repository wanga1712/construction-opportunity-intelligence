#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path_tabs = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/tabs.py"
with open(path_tabs, "r", encoding="utf-8") as f:
    code_tabs = f.read()

target = 'def _reset_torgi_page() -> None:\n    st.session_state["torgi_workset_page"] = 1'
replacement = """def _reset_torgi_page() -> None:
    st.session_state["torgi_workset_page"] = 1
    for k in list(st.session_state.keys()):
        if "torgi_workset_page" in k:
            st.session_state[k] = 1"""

assert target in code_tabs, "target _reset_torgi_page not found in tabs.py"
code_tabs = code_tabs.replace(target, replacement)

with open(path_tabs, "w", encoding="utf-8") as f:
    f.write(code_tabs)

print("UPDATED _reset_torgi_page TO RESET ALL TORGI PAGE KEYS IN SESSION STATE!")
PYEOF
