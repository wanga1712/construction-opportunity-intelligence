from src.bootstrap import setup_source_path
setup_source_path()

import os
import psycopg2
from src.services.db_bootstrap import connect_databases
from src.services.commercial_routing_v3.autonomous_learning_loop import (
    compute_md5,
    HUNTER_PROMPT_VERSION,
    AUDITOR_PROMPT_VERSION
)

def load_dotenv(path="/opt/CRM_Streamlit/.env"):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ[k.strip()] = v.strip()

def main():
    load_dotenv()
    _, _, crm_db, _ = connect_databases()
    if not crm_db:
        print("Failed to connect to CRM DB")
        return
        
    pid = 900000150
    print(f"=== ANALYSIS FOR {pid} ===")
    
    # 1. Fetch from crm_v3_autonomous_analysis_traces
    traces = crm_db.execute_query("""
        SELECT source_snapshot_hash, document_set_hash, extracted_evidence_hash, registry_hash, hunter_prompt_version, auditor_prompt_version, model_version
        FROM crm_v3_autonomous_analysis_traces 
        WHERE procurement_id = %s
    """, (pid,))
    
    if traces:
        db_trace = traces[0]
        print("DB Trace:")
        print("  source_snapshot_hash:   ", db_trace.get("source_snapshot_hash"))
        print("  document_set_hash:      ", db_trace.get("document_set_hash"))
        print("  extracted_evidence_hash:", db_trace.get("extracted_evidence_hash"))
        print("  registry_hash:          ", db_trace.get("registry_hash"))
        print("  hunter_prompt_version:  ", db_trace.get("hunter_prompt_version"))
        print("  auditor_prompt_version: ", db_trace.get("auditor_prompt_version"))
        print("  model_version:          ", db_trace.get("model_version"))
    else:
        print("No trace found in DB!")

    # 2. Recompute worker-side hashes
    from src.services.commercial_routing_v3.autonomous_learning_loop import HunterAuditorOrchestrator
    orchestrator = HunterAuditorOrchestrator(crm_db)
    
    facts = orchestrator.fetch_procurement_facts(pid)
    source_snapshot_hash = compute_md5(facts)
    docs, doc_set_hash = orchestrator.fetch_document_research_summary(pid)
    evidence = orchestrator.fetch_document_evidence(pid)
    evidence_hash = compute_md5(evidence)
    registry = orchestrator.load_active_categories()
    reg_hash = orchestrator.compute_registry_hash(registry)
    
    print("\nWorker computed:")
    print("  source_snapshot_hash:   ", source_snapshot_hash)
    print("  document_set_hash:      ", doc_set_hash)
    print("  extracted_evidence_hash:", evidence_hash)
    print("  registry_hash:          ", reg_hash)
    print("  hunter_prompt_version:  ", HUNTER_PROMPT_VERSION)
    print("  auditor_prompt_version: ", AUDITOR_PROMPT_VERSION)
    print("  model_version:           qwen2.5:7b")

if __name__ == '__main__':
    main()
