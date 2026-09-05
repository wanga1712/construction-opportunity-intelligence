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
from src.services.commercial_routing_v3.factual_feeder import FactualFeeder, _get_doc_db_conn, PIPELINE_GENERATION
from src.services.commercial_routing_v3.autonomous_learning_loop import HunterAuditorOrchestrator

tender_db, radar_db, crm_db, _ = connect_databases()
feeder = FactualFeeder(crm_db)
orchestrator = HunterAuditorOrchestrator(crm_db)

canary_44 = [129606, 116536, 116375, 106994, 106637, 105689, 84475, 80973, 76859, 76286]
canary_223 = [152663, 144476, 142543, 142413, 142394, 139805, 139789, 136065, 136057, 127742]
canary_all = canary_44 + canary_223

print("=== ADMITTING 20 CANARY PROCUREMENTS VIA FACTUAL FEEDER ===")
for pid in canary_all:
    procs = crm_db.execute_query("SELECT * FROM crm_procurements WHERE id = %s", (pid,))
    if procs:
        proc = procs[0]
        res = feeder.admit_procurement(proc)
        print(f"Procurement {pid} ({proc.get('source_table')}): admitted={res.get('admitted')}, docs={res.get('canonical_doc_count')}")

# Ensure queue status is COMPLETED for canary set
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
conn.commit()
conn.close()

print("\n=== RUNNING HUNTER-AUDITOR ANALYSIS LOOP FOR CANARY SET ===")
results = []
for pid in canary_all:
    print(f"--- Processing Canary Procurement {pid} ---")
    try:
        res = orchestrator.run_learning_loop(pid)
        print(f"  Result: {json.dumps(res, default=str, ensure_ascii=False)}")
        results.append((pid, res))
    except Exception as e:
        print(f"  Error on procurement {pid}: {e}")

with open("/tmp/_canary_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, default=str, ensure_ascii=False, indent=2)

print("\n=== CANARY RUN COMPLETE ===")

PYEOF
