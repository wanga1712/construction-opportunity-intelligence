#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path_loop = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/autonomous_learning_loop.py"

with open(path_loop, "r", encoding="utf-8") as f:
    code = f.read()

target = '''    def _get_doc_conn(self):
        pwd_env = os.getenv("S13_DOCUMENT_DB_PASSWORD", "")'''

replacement = '''    def _get_doc_conn(self):
        from src.services.commercial_routing_v3.queue_producer import _load_doc_env
        _load_doc_env()
        pwd_env = os.getenv("S13_DOCUMENT_DB_PASSWORD", "")'''

assert target in code, "_get_doc_conn target not found in autonomous_learning_loop.py"
code = code.replace(target, replacement)

with open(path_loop, "w", encoding="utf-8") as f:
    f.write(code)

print("UPDATED autonomous_learning_loop.py WITH _load_doc_env() CALL!")

path_feeder = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/factual_feeder.py"
with open(path_feeder, "r", encoding="utf-8") as f:
    code_feeder = f.read()

target_feeder = '''def _get_doc_db_conn():
    dsn = {'''

replacement_feeder = '''def _get_doc_db_conn():
    from src.services.commercial_routing_v3.queue_producer import _load_doc_env
    _load_doc_env()
    dsn = {'''

assert target_feeder in code_feeder, "_get_doc_db_conn target not found in factual_feeder.py"
code_feeder = code_feeder.replace(target_feeder, replacement_feeder)

with open(path_feeder, "w", encoding="utf-8") as f:
    f.write(code_feeder)

print("UPDATED factual_feeder.py WITH _load_doc_env() CALL!")

PYEOF
