#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/autonomous_learning_loop.py"
with open(path, "r", encoding="utf-8") as f:
    code = f.read()

code = code.replace('return "\\n".join(lines)\n".join(lines)', 'return "\\n".join(lines)')
with open(path, "w", encoding="utf-8") as f:
    f.write(code)

print("FIXED DUP RETURN IN autonomous_learning_loop.py!")
PYEOF
