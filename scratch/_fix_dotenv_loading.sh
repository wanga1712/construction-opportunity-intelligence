#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path_feeder = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/factual_feeder.py"
with open(path_feeder, "r", encoding="utf-8") as f:
    code_f = f.read()

target = '''def _get_doc_db_conn():
    dsn = {'''

replacement = '''def _get_doc_db_conn():
    from dotenv import load_dotenv
    load_dotenv('/opt/CRM_Streamlit/.env')
    dsn = {'''

assert target in code_f, "target not found in factual_feeder.py"
code_f = code_f.replace(target, replacement)
with open(path_feeder, "w", encoding="utf-8") as f:
    f.write(code_f)

print("UPDATED factual_feeder.py WITH load_dotenv CALL!")

path_loop = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/autonomous_learning_loop.py"
with open(path_loop, "r", encoding="utf-8") as f:
    code_l = f.read()

target_l = '''    def _get_doc_conn(self):
        dsn = dict(self._doc_dsn)'''

replacement_l = '''    def _get_doc_conn(self):
        from dotenv import load_dotenv
        load_dotenv('/opt/CRM_Streamlit/.env')
        dsn = dict(self._doc_dsn)'''

assert target_l in code_l, "target_l not found in autonomous_learning_loop.py"
code_l = code_l.replace(target_l, replacement_l)
with open(path_loop, "w", encoding="utf-8") as f:
    f.write(code_l)

print("UPDATED autonomous_learning_loop.py WITH load_dotenv CALL!")

PYEOF
