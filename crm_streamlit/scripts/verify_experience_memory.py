"""Retrieve and print Experience Memory stats for 5 actual category groups."""
import os
import sys
import logging

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.bootstrap import setup_source_path
setup_source_path()

from src.services.db_bootstrap import connect_databases
from src.services.commercial_routing_v3.experience_memory import ExperienceMemory

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("verify_experience_memory")

def main():
    _, _, crm_db, _ = connect_databases()
    
    memory = ExperienceMemory(crm_db)
    stats = memory.get_category_stats()
    
    # Sort categories to find ones with most observations/findings
    stats.sort(key=lambda s: s["machine_found"] + s["observations"], reverse=True)
    
    print("====== EXPERIENCE MEMORY priors ======")
    for s in stats[:5]:
        print(f"\nCATEGORY={s['category_code']} ({s['category_name']})")
        print(f"OBSERVATIONS={s['observations']}")
        print(f"MACHINE_PRESENT={s['machine_found']}")
        print(f"AUDITOR_CONFIRMED={s['auditor_confirmed']}")
        print(f"HUMAN_CONFIRMED={s['human_confirmed']}")
        print(f"HUMAN_REJECTED={s['human_rejected']}")
        print(f"COMPLETE_RESEARCH_NOT_FOUND={s['not_found_complete']}")
        print(f"PARTIAL_UNKNOWN={s['unknown_partial']}")
        print(f"NO_DOCUMENTS={s['no_documents']}")

if __name__ == "__main__":
    main()
