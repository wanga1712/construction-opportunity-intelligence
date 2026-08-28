"""Autonomous worker daemon.

Polls for completed document processing tasks and executes the Hunter-Auditor
LLM analysis loop sequentially to establish product evidence and consensus.
"""
from __future__ import annotations

import logging
import os
import time
import signal
import sys
from typing import Any

from src.services.commercial_routing_v3.autonomous_learning_loop import HunterAuditorOrchestrator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("autonomous_worker")

class AutonomousWorker:
    """Daemon worker that polls completed document tasks and runs Hunter-Auditor loop."""

    def __init__(self, crm_db: Any) -> None:
        self.crm_db = crm_db
        self.orchestrator = HunterAuditorOrchestrator(crm_db)
        self.running = True

    def stop(self) -> None:
        logger.info("Stopping autonomous worker...")
        self.running = False

    def run_once(self) -> int:
        """Poll and process one pending learning task.

        Returns 1 if a task was processed, 0 otherwise.
        """
        # Find a procurement that has a completed queue task in document_processing_queue
        # but does not have a trace in crm_v3_autonomous_analysis_traces yet.
        # We query the document_intelligence DB schema mapping via crm_db connection
        # (since crm_db can execute arbitrary SQL if we use cross-DB query or link, 
        # or we query using the orchestrator's document DB connection).
        
        doc_conn = self.orchestrator._get_doc_conn()
        procurement_id = None
        try:
            with doc_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT procurement_id 
                    FROM document_processing_queue
                    WHERE status = 'COMPLETED'
                      AND pipeline_generation = 'S13_V2'
                    ORDER BY id DESC
                    LIMIT 100
                    """
                )
                rows = cur.fetchall()
                completed_ids = [r[0] for r in rows]
        finally:
            doc_conn.close()

        if not completed_ids:
            return 0

        # Filter out those that already have a trace in CRM DB
        for pid in completed_ids:
            exists = self.crm_db.execute_scalar(
                "SELECT 1 FROM crm_v3_autonomous_analysis_traces WHERE procurement_id = %s LIMIT 1",
                (pid,)
            )
            if not exists:
                procurement_id = pid
                break

        if procurement_id is None:
            return 0

        logger.info(f"Picked up procurement {procurement_id} for autonomous LLM analysis...")
        
        try:
            # Load experience priors context
            priors_text = ""
            try:
                # We can query some summaries or priors for this procurement
                facts = self.orchestrator.fetch_procurement_facts(procurement_id)
                okpd = facts.get("okpd_code") or ""
                priors_rows = self.crm_db.execute_query(
                    """
                    SELECT category_code, machine_found, human_confirmed, human_rejected
                    FROM crm_v3_reward_ledgerrl  -- Or we compute from experience memory
                    LIMIT 0
                    """
                ) # Placeholder or empty priors if none yet
            except Exception:
                priors_text = "No historical priors."

            # Run the Hunter-Auditor learning loop
            result = self.orchestrator.run_learning_loop(procurement_id, priors_text)
            logger.info(f"Successfully processed procurement {procurement_id}. Consensus: {result['consensus_state']}")
            return 1
        except Exception as exc:
            logger.error(f"Error processing procurement {procurement_id}: {exc}", exc_info=True)
            # To prevent infinite loop on poison pill, write a trace indicating failure
            try:
                self.crm_db.execute_update(
                    """
                    INSERT INTO crm_v3_autonomous_analysis_traces (
                        procurement_id, consensus_state
                    ) VALUES (%s, 'FAILED_PROCESSING')
                    """,
                    (procurement_id,)
                )
            except Exception as trace_exc:
                logger.error(f"Failed to record failed trace: {trace_exc}")
            return 1

    def run_forever(self, sleep_seconds: int = 5) -> None:
        """Daemon main loop."""
        logger.info("Autonomous learning loop worker started.")
        while self.running:
            processed = 0
            try:
                processed = self.run_once()
            except Exception as exc:
                logger.error(f"Error in daemon loop: {exc}", exc_info=True)
            
            if processed == 0:
                time.sleep(sleep_seconds)

if __name__ == "__main__":
    # Standard DB connection bootstrap when run as a standalone process
    import os
    import sys
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
    from src.bootstrap import setup_source_path
    setup_source_path()

    from src.services.db_bootstrap import connect_databases
    _, _, db, _ = connect_databases()
    
    # Adapt simple execute_query interface for DatabaseManager
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

    crm_wrapper = CRMDBWrapper(db)
    worker = AutonomousWorker(crm_wrapper)

    def sigterm_handler(signum, frame):
        worker.stop()

    signal.signal(signal.SIGINT, sigterm_handler)
    signal.signal(signal.SIGTERM, sigterm_handler)

    worker.run_forever()
