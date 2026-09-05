#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path_loop = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/autonomous_learning_loop.py"

with open(path_loop, "r", encoding="utf-8") as f:
    code = f.read()

target = '''        self._doc_dsn = {
            "host":     os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
            "port":     int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
            "dbname":   os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
            "user":     os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        }'''

replacement = '''        self._doc_dsn = {
            "host":     os.getenv("S13_DOCUMENT_DB_HOST") if os.getenv("S13_DOCUMENT_DB_HOST") not in (None, "", "S7") else "127.0.0.1",
            "port":     int(os.getenv("S13_DOCUMENT_DB_PORT") or os.getenv("CRM_DB_PORT") or "5432"),
            "dbname":   "document_intelligence",
            "user":     os.getenv("CRM_DB_USER") or "crm_app",
            "password": os.getenv("CRM_DB_PASSWORD") or "",
        }'''

assert target in code, "self._doc_dsn target not found in autonomous_learning_loop.py"
code = code.replace(target, replacement)

target_get = '''    def _get_doc_conn(self):
        from src.services.commercial_routing_v3.queue_producer import _load_doc_env
        _load_doc_env()
        pwd_env = os.getenv("S13_DOCUMENT_DB_PASSWORD", "")
        dsn = dict(self._doc_dsn)
        dsn["password"] = pwd_env
        return psycopg2.connect(**dsn)'''

replacement_get = '''    def _get_doc_conn(self):
        dsn = dict(self._doc_dsn)
        return psycopg2.connect(**dsn)'''

assert target_get in code, "_get_doc_conn target not found"
code = code.replace(target_get, replacement_get)

with open(path_loop, "w", encoding="utf-8") as f:
    f.write(code)

print("UPDATED _doc_dsn IN autonomous_learning_loop.py TO USE crm_app CREDITENTIALS!")

path_feeder = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/factual_feeder.py"
with open(path_feeder, "r", encoding="utf-8") as f:
    code_feeder = f.read()

target_f = '''def _get_doc_db_conn():
    from src.services.commercial_routing_v3.queue_producer import _load_doc_env
    _load_doc_env()
    dsn = {
        "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }
    return psycopg2.connect(**dsn)'''

replacement_f = '''def _get_doc_db_conn():
    dsn = {
        "host": os.getenv("S13_DOCUMENT_DB_HOST") if os.getenv("S13_DOCUMENT_DB_HOST") not in (None, "", "S7") else "127.0.0.1",
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT") or os.getenv("CRM_DB_PORT") or "5432"),
        "dbname": "document_intelligence",
        "user": os.getenv("CRM_DB_USER") or "crm_app",
        "password": os.getenv("CRM_DB_PASSWORD") or "",
    }
    return psycopg2.connect(**dsn)'''

assert target_f in code_feeder, "target_f not found in factual_feeder.py"
code_feeder = code_feeder.replace(target_f, replacement_f)

with open(path_feeder, "w", encoding="utf-8") as f:
    f.write(code_feeder)

print("UPDATED _get_doc_db_conn IN factual_feeder.py TO USE crm_app CREDENTIALS!")

PYEOF
