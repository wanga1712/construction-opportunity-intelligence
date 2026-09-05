#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path_loop = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/autonomous_learning_loop.py"

with open(path_loop, "r", encoding="utf-8") as f:
    code = f.read()

# Replace simple prefix truncation evidence[:100] in build_hunter_prompt and build_auditor_prompt
old_hunter_trunc = "evidence_str = self.format_evidence_for_prompt(evidence[:100])"
new_hunter_trunc = "evidence_str = self.format_evidence_for_prompt(evidence)"

assert old_hunter_trunc in code, "evidence[:100] not found in autonomous_learning_loop.py"

code = code.replace(old_hunter_trunc, new_hunter_trunc)

with open(path_loop, "w", encoding="utf-8") as f:
    f.write(code)

print("UPDATED autonomous_learning_loop.py TO REMOVE SIMPLE PREFIX TRUNCATION evidence[:100]!")
PYEOF
