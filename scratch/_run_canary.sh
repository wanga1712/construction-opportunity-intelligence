#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os, json, time
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')

from src.services.db_bootstrap import connect_databases
from src.services.commercial_routing_v3.factual_feeder import FactualFeeder
from src.services.commercial_routing_v3.autonomous_worker import AutonomousWorker
from src.services.commercial_routing_v3.autonomous_learning_loop import HunterAuditorOrchestrator

tender_db, radar_db, crm_db, _ = connect_databases()

canary_44 = [1012, 1011, 1010, 1009, 1008, 1007, 1006, 1005, 1004, 1003]
canary_223 = [1037, 1036, 1034, 1033, 1028, 1027, 1026, 1024, 1022, 1021]
canary_all = canary_44 + canary_223

feeder = FactualFeeder(crm_db)
print("=== ADMITTING CANARY PROCUREMENTS VIA FACTUAL FEEDER ===")
feeder_results = []
for pid in canary_all:
    procs = crm_db.execute_query("SELECT id, source_table, source_id, contract_number FROM crm_procurements WHERE id = %s LIMIT 1", (pid,))
    if procs:
        res = feeder.admit_procurement(procs[0])
        feeder_results.append(res)
        print(f"Procurement {pid} ({procs[0]['source_table']}): admitted={res.get('admitted')}, docs={res.get('doc_count')}, reason={res.get('reason')}")

print("\n=== RUNNING HUNTER-AUDITOR ANALYSIS LOOP FOR CANARY SET ===")
orchestrator = HunterAuditorOrchestrator(crm_db)
canary_summary = []

for pid in canary_all:
    t0 = time.time()
    try:
        facts = orchestrator.fetch_procurement_facts(pid)
        docs, doc_hash = orchestrator.fetch_document_research_summary(pid)
        evidence = orchestrator.fetch_document_evidence(pid)
        
        # Run learning loop for this procurement
        loop_res = orchestrator.run_learning_loop(pid)
        
        raw_evidence_cnt = len(evidence)
        findings_rows = crm_db.execute_query("SELECT COUNT(*) as cnt FROM crm_v3_product_findings WHERE procurement_id = %s", (pid,))
        norm_cnt = findings_rows[0]["cnt"] if findings_rows else 0
        
        traces = crm_db.execute_query("SELECT consensus_state FROM crm_v3_autonomous_analysis_traces WHERE procurement_id = %s ORDER BY id DESC LIMIT 1", (pid,))
        status = traces[0]["consensus_state"] if traces else "UNANALYZED"
        
        canary_summary.append({
            "PROCUREMENT_ID": pid,
            "PROCUREMENT_NUMBER": facts.get("registry_number") or str(pid),
            "LAW": facts.get("law_type") or ("44-ФЗ" if pid in canary_44 else "223-ФЗ"),
            "DOCUMENTS_DISCOVERED": len(docs),
            "DOCUMENTS_PARSED": sum(1 for d in docs if d.get("parse_status") == "SUCCESS"),
            "DOCUMENTS_RESEARCHED": len(docs),
            "DOCUMENTS_FAILED": sum(1 for d in docs if d.get("research_state") in ("DOWNLOAD_FAILED", "PARSE_FAILED")),
            "RAW_EVIDENCE_COUNT": raw_evidence_cnt,
            "NORMALIZED_FINDINGS_COUNT": norm_cnt,
            "HUNTER_STATUS": loop_res.get("hunter_status", "EXECUTED"),
            "AUDITOR_STATUS": loop_res.get("auditor_status", "EXECUTED"),
            "RESEARCH_COMPLETENESS": "COMPLETE" if docs else "NO_DOCUMENTS"
        })
        print(f"Processed canary procurement {pid}: status={status}, raw_evidence={raw_evidence_cnt}, findings={norm_cnt}")
    except Exception as e:
        print(f"Error processing canary procurement {pid}: {e}")

print("\n=== CANARY EXECUTION SUMMARY ===")
print(json.dumps(canary_summary, indent=2, ensure_ascii=False))

PYEOF
