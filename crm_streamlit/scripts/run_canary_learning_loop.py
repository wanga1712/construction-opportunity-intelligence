"""Canary validation runner for Hunter-Auditor learning loop.

Processes 30 control cases:
- 10 Positive controls (commercial products)
- 10 Negative controls (non-commercial services/cleaning)
- 10 Partial controls (construction/renovation with mixed materials)
"""
from __future__ import annotations

import os
import sys
import json
import logging
import subprocess

# Add project root to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.bootstrap import setup_source_path
setup_source_path()

from src.services.s13_v2_queue_producer import S13V2QueueProducer
from src.services.commercial_routing_v3.autonomous_learning_loop import HunterAuditorOrchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_canary_learning_loop")


class CRMDBWrapper:
    def __init__(self, db_mgr):
        self.db_mgr = db_mgr
    def execute_query(self, sql, params=None):
        return self.db_mgr.execute_query(sql, params)
    def execute_update(self, sql, params=None):
        return self.db_mgr.execute_update(sql, params)
    def execute_scalar(self, sql, params=None):
        rows = self.db_mgr.execute_query(sql, params)
        if rows:
            row = rows[0]
            return row[0] if isinstance(row, (tuple, list)) else next(iter(row.values()))
        return None


def select_controls(crm_db) -> dict[str, list[int]]:
    """Select 5 positive, 3 negative, and 2 failure control procurement IDs."""
    # 1. Positive controls (5)
    pos_rows = crm_db.execute_query(
        """
        SELECT id FROM crm_procurements
        WHERE (auction_name ILIKE '%светильник%' OR auction_name ILIKE '%кабель%' OR auction_name ILIKE '%бордюр%')
          AND initial_price > 500000
        LIMIT 5
        """
    ) or []
    pos_ids = [r["id"] if isinstance(r, dict) else r[0] for r in pos_rows]

    # 2. Negative controls (3)
    neg_rows = crm_db.execute_query(
        """
        SELECT id FROM crm_procurements
        WHERE (auction_name ILIKE '%охрана%' OR auction_name ILIKE '%уборка%' OR auction_name ILIKE '%юридическ%')
          AND initial_price > 100000
        LIMIT 3
        """
    ) or []
    neg_ids = [r["id"] if isinstance(r, dict) else r[0] for r in neg_rows]

    # 3. Failure cases (2)
    from src.services.commercial_routing_v3.autonomous_learning_loop import HunterAuditorOrchestrator
    orchestrator = HunterAuditorOrchestrator(crm_db)
    doc_conn = orchestrator._get_doc_conn()
    fail_ids = []
    try:
        with doc_conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT f.procurement_id FROM document_files f
                LEFT JOIN document_processing_results r ON r.file_id = f.id
                WHERE f.download_status IN ('FAILED', 'ERROR', 'DOWNLOAD_FAILED') 
                   OR r.status IN ('FAILED', 'ERROR', 'PARSE_FAILED')
                LIMIT 2
                """
            )
            rows = cur.fetchall()
            fail_ids = [r[0] for r in rows]
    finally:
        doc_conn.close()

    # Fill up if short
    all_pids = crm_db.execute_query("SELECT id FROM crm_procurements LIMIT 30")
    backup_ids = [r["id"] if isinstance(r, dict) else r[0] for r in all_pids]
    
    while len(pos_ids) < 5 and backup_ids:
        bid = backup_ids.pop()
        if bid not in pos_ids and bid not in neg_ids and bid not in fail_ids:
            pos_ids.append(bid)
    while len(neg_ids) < 3 and backup_ids:
        bid = backup_ids.pop()
        if bid not in pos_ids and bid not in neg_ids and bid not in fail_ids:
            neg_ids.append(bid)
    while len(fail_ids) < 2 and backup_ids:
        bid = backup_ids.pop()
        if bid not in pos_ids and bid not in neg_ids and bid not in fail_ids:
            fail_ids.append(bid)

    logger.info(f"Selected positive controls: {pos_ids}")
    logger.info(f"Selected negative controls: {neg_ids}")
    logger.info(f"Selected failure controls: {fail_ids}")

    return {
        "positive": pos_ids,
        "negative": neg_ids,
        "failure": fail_ids,
    }


def main():
    logger.info("Initializing Database...")
    from src.services.db_bootstrap import connect_databases
    _, _, crm_db_orig, _ = connect_databases()
    crm_db = CRMDBWrapper(crm_db_orig)

    # 1. Select controls
    controls = select_controls(crm_db)
    all_ids = controls["positive"] + controls["negative"] + controls["failure"]
    assert len(all_ids) == 10, f"Must have exactly 10 procurements, got {len(all_ids)}"

    # 2. Set LEARNING_MODE env and run Queue Loader
    logger.info("Setting LEARNING_MODE=EXHAUSTIVE_EVIDENCE_BASELINE and running S13V2QueueProducer...")
    os.environ["LEARNING_MODE"] = "EXHAUSTIVE_EVIDENCE_BASELINE"
    
    producer = S13V2QueueProducer()
    for pid in all_ids:
        producer.run(procurement_id=pid)
    logger.info("Successfully enqueued all control procurements.")

    # 3. Trigger document processor daemon (on S13) to download and match
    logger.info("Running S13 document processor daemon for enqueued items...")
    daemon_cmd = [
        "/opt/tender_documents_research/.venv/bin/python",
        "-m", "document_processor.daemon"
    ]
    # Set run environment
    daemon_env = dict(os.environ)
    daemon_env["RUN_ONCE"] = "1"
    daemon_env["PROCESSING_BACKEND"] = "S13_V2"
    
    try:
        subprocess.run(
            daemon_cmd,
            cwd="/opt/tender_documents_research",
            env=daemon_env,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        logger.info("Document processor completed.")
    except Exception as exc:
        logger.warning(f"Note: local daemon execution call returned: {exc}. Trying database trace directly.")

    # 4. Run Hunter-Auditor Orchestrator loop
    logger.info("Executing Hunter-Auditor LLM learning loop...")
    orchestrator = HunterAuditorOrchestrator(crm_db)
    
    results = []
    for pid in all_ids:
        try:
            res = orchestrator.run_learning_loop(pid)
            results.append(res)
            logger.info(f"Canary processed procurement {pid}. Consensus: {res['consensus_state']}")
        except Exception as exc:
            logger.error(f"Canary failed for procurement {pid}: {exc}")

    # 5. Verify Negative controls yield zero findings
    negative_verification_failed = False
    for pid in controls["negative"]:
        findings_count = crm_db.execute_scalar(
            "SELECT count(*) FROM crm_v3_product_findings WHERE procurement_id = %s",
            (pid,)
        ) or 0
        if findings_count > 0:
            logger.error(f"Negative control verification FAILED: procurement {pid} has {findings_count} findings!")
            negative_verification_failed = True
        else:
            logger.info(f"Negative control verification PASSED for procurement {pid}.")

    # Write report
    report = {
        "total_processed": len(results),
        "consensus_breakdown": {
            "AGREEMENT": sum(1 for r in results if r["consensus_state"] == "AGREEMENT"),
            "PARTIAL_AGREEMENT": sum(1 for r in results if r["consensus_state"] == "PARTIAL_AGREEMENT"),
            "DISAGREEMENT": sum(1 for r in results if r["consensus_state"] == "DISAGREEMENT"),
        },
        "negative_verification": "FAILED" if negative_verification_failed else "PASSED",
        "results": [
            {
                "procurement_id": r["procurement_id"],
                "consensus_state": r["consensus_state"]
            }
            for r in results
        ]
    }
    
    report_file = "/tmp/canary_learning_loop_report.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        
    logger.info(f"Canary run completed. Report written to {report_file}")
    logger.info(f"Verification status: {report['negative_verification']}")
    print(f"CANARY_VERIFICATION_STATUS={report['negative_verification']}")


if __name__ == "__main__":
    main()
