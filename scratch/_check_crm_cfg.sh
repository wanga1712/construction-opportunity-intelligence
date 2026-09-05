#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

from src.services.db_bootstrap import connect_databases

tender_db, radar_db, crm_db, _ = connect_databases()
print("CRM DB HOST:", getattr(crm_db, "host", None) or getattr(crm_db.config, "host", None))
print("CRM DB USER:", getattr(crm_db, "user", None) or getattr(crm_db.config, "user", None))
print("CRM DB PWD:", bool(getattr(crm_db, "password", None) or getattr(crm_db.config, "password", None)))
print("CRM DB DSN:", crm_db._get_connection_params() if hasattr(crm_db, "_get_connection_params") else "N/A")

PYEOF
