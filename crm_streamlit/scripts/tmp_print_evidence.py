import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.bootstrap import setup_source_path
setup_source_path()

from src.services.db_bootstrap import connect_databases
from src.services.commercial_routing_v3.autonomous_learning_loop import HunterAuditorOrchestrator
from modules.crm.crm_database import CrmDatabaseManager

def main():
    _, _, crm_db, _ = connect_databases()
    orchestrator = HunterAuditorOrchestrator(crm_db)
    
    procurement_id = 273
    evidence = orchestrator.fetch_document_evidence(procurement_id)
    formatted = orchestrator.format_evidence_for_prompt(evidence[:3])
    
    print("Formatted evidence for procurement 273:")
    print(formatted)

if __name__ == "__main__":
    main()
