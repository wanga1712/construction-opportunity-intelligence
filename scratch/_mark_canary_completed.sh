#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

from src.services.commercial_routing_v3.factual_feeder import _get_doc_db_conn, PIPELINE_GENERATION

canary_44 = [1012, 1011, 1010, 1009, 1008, 1007, 1006, 1005, 1004, 1003]
canary_223 = [1037, 1036, 1034, 1033, 1028, 1027, 1026, 1024, 1022, 1021]
canary_all = canary_44 + canary_223

conn = _get_doc_db_conn()
cur = conn.cursor()

cur.execute(
    """
    UPDATE document_processing_queue
    SET status = 'COMPLETED'
    WHERE procurement_id = ANY(%s) AND pipeline_generation = %s
    """,
    (canary_all, PIPELINE_GENERATION)
)
updated = cur.rowcount
conn.commit()
conn.close()

print(f"UPDATED {updated} CANARY QUEUE TASKS TO STATUS='COMPLETED' FOR AUTONOMOUS WORKER PROCESSING!")

PYEOF
