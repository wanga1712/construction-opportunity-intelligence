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
        doc_conn = self.orchestrator._get_doc_conn()
        tasks = []
        try:
            with doc_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT procurement_id, status 
                    FROM document_processing_queue
                    WHERE status IN ('COMPLETED', 'FAILED', 'NO_LINKS')
                      AND pipeline_generation = 'S13_V2'
                    ORDER BY id DESC
                    LIMIT 100
                    """
                )
                rows = cur.fetchall()
                tasks = [(r[0], r[1]) for r in rows]
        finally:
            doc_conn.close()

        if not tasks:
            return 0

        # Load registry to compute active registry hash
        registry = self.orchestrator.load_active_categories()
        reg_hash = self.orchestrator.compute_registry_hash(registry)
        model_version = "qwen2.5:7b"
        from src.services.commercial_routing_v3.autonomous_learning_loop import (
            HUNTER_PROMPT_VERSION,
            AUDITOR_PROMPT_VERSION,
        )

        picked_task = None
        for pid, q_status in tasks:
            # Check versioned trace status
            trace = self.crm_db.execute_query_one(
                """
                SELECT id, attempt_count, consensus_state
                FROM crm_v3_autonomous_analysis_traces
                WHERE procurement_id = %s
                  AND registry_hash = %s
                  AND hunter_prompt_version = %s
                  AND auditor_prompt_version = %s
                  AND model_version = %s
                ORDER BY id DESC LIMIT 1
                """,
                (
                    pid,
                    reg_hash,
                    HUNTER_PROMPT_VERSION,
                    AUDITOR_PROMPT_VERSION,
                    model_version,
                )
            )
            
            if not trace:
                picked_task = (pid, q_status)
                break
            else:
                # If trace exists, check if it's FAILED_PROCESSING and we haven't exceeded retry limit
                if trace["consensus_state"] == "FAILED_PROCESSING":
                    attempts = trace["attempt_count"] or 1
                    if attempts < 3:
                        picked_task = (pid, q_status)
                        logger.info(f"Retrying failed procurement {pid} (previous attempts: {attempts})")
                        break
        
        if picked_task is None:
            return 0

        procurement_id, q_status = picked_task
        logger.info(f"Picked up procurement {procurement_id} with queue status {q_status} for autonomous processing...")
        
        try:
            if q_status == "COMPLETED":
                # Load experience priors context
                priors_text = "EXPERIENCE_PRIORS_TO_HUNTER=DISABLED"

                # Run the Hunter-Auditor learning loop
                result = self.orchestrator.run_learning_loop(procurement_id, priors_text)
                logger.info(f"Successfully processed procurement {procurement_id}. Consensus: {result['consensus_state']}")
            elif q_status == "NO_LINKS":
                # Save trace with research_completeness = 'NO_DOCUMENTS' and consensus_state = 'NO_DOCUMENTS'
                # Do NOT run LLM inference.
                self.orchestrator.save_terminal_trace(
                    procurement_id=procurement_id,
                    consensus_state="NO_DOCUMENTS",
                    research_completeness="NO_DOCUMENTS"
                )
                logger.info(f"Saved terminal trace for procurement {procurement_id} as NO_DOCUMENTS")
            elif q_status == "FAILED":
                # Save trace with research_completeness = 'FAILED' and consensus_state = 'FAILED_PROCESSING'
                # Do NOT run LLM inference.
                self.orchestrator.save_terminal_trace(
                    procurement_id=procurement_id,
                    consensus_state="FAILED_PROCESSING",
                    research_completeness="FAILED"
                )
                logger.info(f"Saved terminal trace for procurement {procurement_id} as FAILED_PROCESSING")
            return 1
        except Exception as exc:
            logger.error(f"Error processing procurement {procurement_id}: {exc}", exc_info=True)
            # To prevent infinite loop on poison pill, write/update a trace indicating failure
            try:
                # Find current attempt count if trace exists
                prev_trace = self.crm_db.execute_query_one(
                    """
                    SELECT attempt_count FROM crm_v3_autonomous_analysis_traces
                    WHERE procurement_id = %s
                      AND registry_hash = %s
                      AND hunter_prompt_version = %s
                      AND auditor_prompt_version = %s
                      AND model_version = %s
                    ORDER BY id DESC LIMIT 1
                    """,
                    (
                        procurement_id,
                        reg_hash,
                        HUNTER_PROMPT_VERSION,
                        AUDITOR_PROMPT_VERSION,
                        model_version,
                    )
                )
                attempt = 1
                if prev_trace:
                    attempt = (prev_trace["attempt_count"] or 1) + 1
                
                self.crm_db.execute_update(
                    """
                    INSERT INTO crm_v3_autonomous_analysis_traces (
                        procurement_id, source_snapshot_hash, document_set_hash,
                        extracted_evidence_hash, consensus_state, research_completeness,
                        registry_hash, hunter_prompt_version, auditor_prompt_version,
                        model_version, attempt_count, last_error
                    ) VALUES (%s, NULL, NULL, NULL, 'FAILED_PROCESSING', 'FAILED', %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        procurement_id,
                        reg_hash,
                        HUNTER_PROMPT_VERSION,
                        AUDITOR_PROMPT_VERSION,
                        model_version,
                        attempt,
                        str(exc)
                    )
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
        def execute_query_one(self, sql, params=None):
            rows = self.db_mgr.execute_query(sql, params)
            return rows[0] if rows else None
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
