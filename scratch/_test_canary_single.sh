#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os, json, time
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

from src.services.db_bootstrap import connect_databases
from src.services.commercial_routing_v3.autonomous_learning_loop import HunterAuditorOrchestrator

tender_db, radar_db, crm_db, _ = connect_databases()
orchestrator = HunterAuditorOrchestrator(crm_db)

# Process procurement 1012 directly
pid = 1012
print(f"=== PROCESSING CANARY PROC {pid} ===")
facts = orchestrator.fetch_procurement_facts(pid)
docs, doc_hash = orchestrator.fetch_document_research_summary(pid)
evidence = orchestrator.fetch_document_evidence(pid)

print(f"Facts: id={pid}, number={facts.get('contract_number')}, law={facts.get('law_type')}")
print(f"Docs count: {len(docs)}")
print(f"Raw evidence count: {len(evidence)}")

if evidence:
    print(f"Sample raw evidence item 0: {json.dumps(evidence[0], indent=2, ensure_ascii=False)}")

# Run learning loop for pid
loop_res = orchestrator.run_learning_loop(pid)
print(f"Loop result for {pid}: {json.dumps(loop_res, indent=2, ensure_ascii=False)}")

findings = crm_db.execute_query("SELECT * FROM crm_v3_product_findings WHERE procurement_id = %s", (pid,))
print(f"Findings count: {len(findings or [])}")
if findings:
    print("Sample finding:", json.dumps(findings[0], indent=2, ensure_ascii=False, default=str))

PYEOF
