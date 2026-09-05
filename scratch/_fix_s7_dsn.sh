#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path_dl = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/document_links.py"
with open(path_dl, "r", encoding="utf-8") as f:
    code = f.read()

target = """def _s7_dsn() -> Dict[str, Any]:
    return {
        "host": os.getenv("DB_HOST") or os.getenv("TENDER_DB_HOST") or "S7",
        "port": int(os.getenv("DB_PORT") or os.getenv("TENDER_DB_PORT") or 5432),
        "dbname": os.getenv("DB_NAME") or os.getenv("TENDER_DB_DATABASE") or "tender_monitor",
        "user": os.getenv("DB_USER") or os.getenv("TENDER_DB_USER"),
        "password": os.getenv("DB_PASSWORD") or os.getenv("TENDER_DB_PASSWORD") or "",
        "connect_timeout": int(os.getenv("S7_LINK_CONNECT_TIMEOUT", "8")),
    }"""

replacement = """def _s7_dsn() -> Dict[str, Any]:
    return {
        "host": os.getenv("DB_HOST") or os.getenv("TENDER_DB_HOST") or os.getenv("TENDER_MONITOR_DB_HOST") or "10.8.0.7",
        "port": int(os.getenv("DB_PORT") or os.getenv("TENDER_DB_PORT") or os.getenv("TENDER_MONITOR_DB_PORT") or 5432),
        "dbname": os.getenv("DB_NAME") or os.getenv("TENDER_DB_DATABASE") or os.getenv("TENDER_MONITOR_DB_DATABASE") or "tender_monitor",
        "user": os.getenv("DB_USER") or os.getenv("TENDER_DB_USER") or os.getenv("TENDER_MONITOR_DB_USER") or "postgres",
        "password": os.getenv("DB_PASSWORD") or os.getenv("TENDER_DB_PASSWORD") or os.getenv("TENDER_MONITOR_DB_PASSWORD") or "oTIg3EqK85pux8SfZTuCbS-bEcObXiGfV3P2hU2m5uJ_pYMbRtRmP8jnMA-hvyhR",
        "connect_timeout": int(os.getenv("S7_LINK_CONNECT_TIMEOUT", "8")),
    }"""

if target in code:
    code = code.replace(target, replacement)
    with open(path_dl, "w", encoding="utf-8") as f:
        f.write(code)
    print("UPDATED _s7_dsn IN document_links.py!")
else:
    print("ALREADY UPDATED OR TARGET NOT FOUND.")

PYEOF
