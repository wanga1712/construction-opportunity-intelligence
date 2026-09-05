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

from src.services.db_bootstrap import connect_databases
from src.services.commercial_routing_v3.autonomous_learning_loop import HunterAuditorOrchestrator

tender_db, radar_db, crm_db, _ = connect_databases()
orchestrator = HunterAuditorOrchestrator(crm_db)

for pid in [1012, 1021, 1037]:
    docs, doc_hash = orchestrator.fetch_document_research_summary(pid)
    evidence = orchestrator.fetch_document_evidence(pid)
    print(f"Procurement {pid}: docs count={len(docs)}, evidence count={len(evidence)}")

PYEOF
