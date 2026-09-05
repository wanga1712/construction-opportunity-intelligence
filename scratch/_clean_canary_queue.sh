#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')

from src.services.commercial_routing_v3.factual_feeder import _get_doc_db_conn, PIPELINE_GENERATION

canary_44 = [129606, 116536, 116375, 106994, 106637, 105689, 84475, 80973, 76859, 76286]
canary_223 = [152663, 144476, 142543, 142413, 142394, 139805, 139789, 136065, 136057, 127742]
canary_all = canary_44 + canary_223

conn = _get_doc_db_conn()
cur = conn.cursor()
cur.execute("DELETE FROM document_processing_queue WHERE procurement_id = ANY(%s)", (canary_all,))
deleted = cur.rowcount
conn.commit()
conn.close()

print(f"DELETED {deleted} EXISTING QUEUE TASKS FOR FRESH ADMISSION TEST!")

PYEOF
