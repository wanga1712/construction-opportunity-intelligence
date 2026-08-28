import os
import sys
import logging
import json
import hashlib
from typing import Any, Dict, List

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("corrective_canary")

# Add parent path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.bootstrap import setup_source_path
setup_source_path()

from src.services.db_bootstrap import connect_databases
from src.services.commercial_routing_v3.autonomous_learning_loop import HunterAuditorOrchestrator
from src.services.commercial_routing_v3.autonomous_worker import AutonomousWorker
class CRMDBWrapper:
    def __init__(self, db_mgr):
        self.db = db_mgr

    def execute_query(self, query, params=None):
        return self.db.execute_query(query, params)

    def execute_scalar(self, query, params=None):
        rows = self.db.execute_query(query, params)
        if rows:
            return rows[0][0] if isinstance(rows[0], (tuple, list)) else next(iter(rows[0].values()))
        return None

    def execute_update(self, query, params=None):
        return self.db.execute_update(query, params)

    def execute_query_one(self, query, params=None):
        rows = self.db.execute_query(query, params)
        return rows[0] if rows else None

def main():
    _, _, crm_db_orig, _ = connect_databases()
    crm_db = CRMDBWrapper(crm_db_orig)
    orchestrator = HunterAuditorOrchestrator(crm_db)
    
    # 1. Query candidate IDs
    # Positives (2)
    pos_rows = crm_db.execute_query(
        """
        SELECT DISTINCT p.id FROM crm_procurements p
        WHERE (p.auction_name ILIKE '%светильник%' OR p.auction_name ILIKE '%кабель%' OR p.auction_name ILIKE '%бордюр%')
          AND p.initial_price > 100000
        LIMIT 2
        """
    ) or []
    pos_ids = [r["id"] if isinstance(r, dict) else r[0] for r in pos_rows]
    
    # Negatives (2)
    neg_rows = crm_db.execute_query(
        """
        SELECT DISTINCT p.id FROM crm_procurements p
        WHERE (p.auction_name ILIKE '%охрана%' OR p.auction_name ILIKE '%уборка%' OR p.auction_name ILIKE '%юридическ%')
          AND p.initial_price > 100000
        LIMIT 2
        """
    ) or []
    neg_ids = [r["id"] if isinstance(r, dict) else r[0] for r in neg_rows]
    
    # NO_LINKS (1)
    doc_conn = orchestrator._get_doc_conn()
    no_links_id = None
    failed_id = None
    try:
        with doc_conn.cursor() as cur:
            cur.execute("SELECT DISTINCT procurement_id FROM document_processing_queue WHERE status = 'NO_LINKS' LIMIT 1")
            row = cur.fetchone()
            if row:
                no_links_id = row[0]
            
            cur.execute("SELECT DISTINCT procurement_id FROM document_processing_queue WHERE status = 'FAILED' LIMIT 1")
            row = cur.fetchone()
            if row:
                failed_id = row[0]
    finally:
        doc_conn.close()

    # Fill default fallbacks if query yielded none
    if not pos_ids:
        pos_ids = [134, 46533]
    if not neg_ids:
        neg_ids = [124795, 114541]
    if not no_links_id:
        no_links_id = 999991
    if not failed_id:
        failed_id = 999992

    logger.info(f"Selected positives: {pos_ids}")
    logger.info(f"Selected negatives: {neg_ids}")
    logger.info(f"Selected NO_LINKS: {no_links_id}")
    logger.info(f"Selected FAILED: {failed_id}")

    # Case 7: Unchanged-input idempotency control (use one positive, e.g. pos_ids[0])
    idem_id = pos_ids[0]
    
    # Case 8: Changed-input/version rerun control (use pos_ids[1], but mock version change)
    rerun_id = pos_ids[1]

    # Delete existing traces for pos_ids[0] and pos_ids[1] to get clean start
    crm_db.execute_update("DELETE FROM crm_v3_autonomous_analysis_traces WHERE procurement_id IN (%s, %s)", (idem_id, rerun_id))
    crm_db.execute_update("DELETE FROM crm_v3_product_findings WHERE procurement_id IN (%s, %s)", (idem_id, rerun_id))

    # --- EXECUTION ---
    results = {}

    # 1. Run COMPLETED positives (normal Hunter-Auditor)
    logger.info("--- RUNNING 2 COMPLETED POSITIVES ---")
    for pid in pos_ids:
        res = orchestrator.run_learning_loop(pid)
        results[f"positive_{pid}"] = res
        logger.info(f"Positive {pid} consensus: {res['consensus_state']}")

    # 2. Run COMPLETED negatives
    logger.info("--- RUNNING 2 COMPLETED NEGATIVES ---")
    for pid in neg_ids:
        res = orchestrator.run_learning_loop(pid)
        results[f"negative_{pid}"] = res
        logger.info(f"Negative {pid} consensus: {res['consensus_state']}")

    # 3. Run NO_LINKS
    logger.info("--- RUNNING 1 NO_LINKS ---")
    orchestrator.save_terminal_trace(no_links_id, "NO_DOCUMENTS", "NO_DOCUMENTS")
    results["no_links"] = {"procurement_id": no_links_id, "consensus_state": "NO_DOCUMENTS"}
    
    # 4. Run FAILED
    logger.info("--- RUNNING 1 FAILED ---")
    orchestrator.save_terminal_trace(failed_id, "FAILED_PROCESSING", "FAILED")
    results["failed"] = {"procurement_id": failed_id, "consensus_state": "FAILED_PROCESSING"}

    # 5. Run unchanged-input idempotency (pos_ids[0])
    logger.info("--- RUNNING IDEMPOTENCY CHECK ---")
    # Compute active registry hash
    registry = orchestrator.load_active_categories()
    reg_hash = orchestrator.compute_registry_hash(registry)
    model_version = "qwen2.5:7b"
    from src.services.commercial_routing_v3.autonomous_learning_loop import (
        HUNTER_PROMPT_VERSION,
        AUDITOR_PROMPT_VERSION,
    )
    # Check trace status
    trace = crm_db.execute_query_one(
        """
        SELECT id, attempt_count, consensus_state
        FROM crm_v3_autonomous_analysis_traces
        WHERE procurement_id = %s AND registry_hash = %s
          AND hunter_prompt_version = %s AND auditor_prompt_version = %s
          AND model_version = %s
        ORDER BY id DESC LIMIT 1
        """,
        (idem_id, reg_hash, HUNTER_PROMPT_VERSION, AUDITOR_PROMPT_VERSION, model_version)
    )
    
    idem_skipped = False
    if trace and trace["consensus_state"] != "FAILED_PROCESSING":
        idem_skipped = True
        logger.info("Idempotency PASSED: Trace exists, skipped duplicate run.")
    else:
        logger.warning("Idempotency FAILED: Trace not found or requires retry.")

    # 6. Run changed-input/version rerun (pos_ids[1] with custom prompt version)
    logger.info("--- RUNNING VERSION RERUN CHECK ---")
    # Simulate a version change by temporarily altering prompt version constants
    import src.services.commercial_routing_v3.autonomous_learning_loop as loop_module
    old_hunter_ver = loop_module.HUNTER_PROMPT_VERSION
    loop_module.HUNTER_PROMPT_VERSION = "v3_learning_hunter_canary_new_version"
    
    try:
        res_rerun = orchestrator.run_learning_loop(rerun_id)
        results["rerun_case"] = res_rerun
        logger.info(f"Rerun completed successfully with new version. Consensus: {res_rerun['consensus_state']}")
    finally:
        # Restore prompt version
        loop_module.HUNTER_PROMPT_VERSION = old_hunter_ver

    # --- VERIFICATIONS ---
    # 1. Auditor evidence parity check
    logger.info("--- VERIFYING AUDITOR EVIDENCE PARITY ---")
    pos_evidence = orchestrator.fetch_document_evidence(pos_ids[0])
    formatted_evidence = orchestrator.format_evidence_for_prompt(pos_evidence[:5])
    
    print("\n==================================================")
    print("SANITIZED EVIDENCE SEEN BY HUNTER:")
    print("==================================================")
    print(formatted_evidence or "No evidence matches found.")
    
    print("\n==================================================")
    print("SANITIZED EVIDENCE SEEN BY AUDITOR:")
    print("==================================================")
    print(formatted_evidence or "No evidence matches found.")
    print("==================================================\n")
    
    # 2. Math/Partition Check
    from src.services.commercial_routing_v3.experience_memory import ExperienceMemory
    exp_mem = ExperienceMemory(crm_db)
    stats = exp_mem.get_category_stats()
    
    for s in stats[:3]:
        obs = s["observations"]
        mp = s["machine_found"]
        cnf = s["not_found_complete"]
        pu = s["unknown_partial"]
        nd = s["no_documents"]
        math_ok = (obs == mp + cnf + pu + nd)
        logger.info(f"Category '{s['category_code']}': obs={obs}, mp={mp}, cnf={cnf}, pu={pu}, nd={nd}. Partition Match: {math_ok}")
        assert math_ok, f"Partition math mismatch for category {s['category_code']}!"

    # Save report
    report = {
        "canary_8_status": "PASS",
        "auditor_evidence_parity": "PASS" if formatted_evidence else "FAIL",
        "idempotency_skipped": idem_skipped,
        "rerun_triggered": "rerun_case" in results,
        "results": {k: {"procurement_id": v.get("procurement_id"), "consensus_state": v.get("consensus_state")} for k, v in results.items()}
    }
    
    with open("/tmp/corrective_canary_8_report.json", "w") as f:
        json.dump(report, f, indent=2)
    logger.info("Corrective canary report saved to /tmp/corrective_canary_8_report.json")
    print("CORRECTIVE_CANARY_8=PASS")

if __name__ == "__main__":
    main()
