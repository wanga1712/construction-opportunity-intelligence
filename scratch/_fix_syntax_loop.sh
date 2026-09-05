#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/autonomous_learning_loop.py"
with open(path, "r", encoding="utf-8") as f:
    code = f.read()

target = 'return "\\n".join(lines)\n\n    def build_hunter_prompt'
replacement = 'return "\\n".join(lines)\n\n    def build_hunter_prompt'

code = code.replace('return "\\n".join(lines)\n\n    \n    def build_hunter_prompt', 'return "\\n".join(lines)\n\n    def build_hunter_prompt')
code = code.replace('return "\n', 'return "\\n".join(lines)\n')

with open(path, "w", encoding="utf-8") as f:
    f.write(code)

print("FIXED LINE 248 SYNTAX IN autonomous_learning_loop.py!")
PYEOF
