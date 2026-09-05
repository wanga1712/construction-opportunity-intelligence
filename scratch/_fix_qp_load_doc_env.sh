#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path_qp = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/queue_producer.py"

with open(path_qp, "r", encoding="utf-8") as f:
    code = f.read()

target = '''def _load_env_file(path: str) -> None:'''

replacement = '''def _load_doc_env() -> None:
    for f in _DOC_ENV_FILES:
        if os.path.exists(f):
            _load_env_file(f)

def _load_env_file(path: str) -> None:'''

if "_load_doc_env() -> None:" not in code[:1000]:
    assert target in code, "target not found in queue_producer.py"
    code = code.replace(target, replacement, 1)
    with open(path_qp, "w", encoding="utf-8") as f:
        f.write(code)
    print("ADDED MODULE-LEVEL _load_doc_env TO queue_producer.py!")
else:
    print("MODULE-LEVEL _load_doc_env ALREADY PRESENT!")

PYEOF
