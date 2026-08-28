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
        # Load registry to compute active registry hash
        registry = self.orchestrator.load_active_categories()
        reg_hash = self.orchestrator.compute_registry_hash(registry)
        model_version = "qwen2.5:7b"
        from src.services.commercial_routing_v3.autonomous_learning_loop import (
            HUNTER_PROMPT_VERSION,
            AUDITOR_PROMPT_VERSION,
            compute_md5,
        )
        from src.services.commercial_routing_v3.document_links import count_document_links

        doc_conn = self.orchestrator._get_doc_conn()
        last_id = None
        picked_task = None

        while self.running:
            tasks = []
            try:
                with doc_conn.cursor() as cur:
                    if last_id is None:
                        cur.execute(
                            """
                            SELECT id, procurement_id, status 
                            FROM document_processing_queue
                            WHERE status IN ('COMPLETED', 'FAILED', 'NO_LINKS')
                              AND pipeline_generation = 'S13_V2'
                            ORDER BY id DESC
                            LIMIT 100
                            """
                        )
                    else:
                        cur.execute(
                            """
                            SELECT id, procurement_id, status 
                            FROM document_processing_queue
                            WHERE status IN ('COMPLETED', 'FAILED', 'NO_LINKS')
                              AND pipeline_generation = 'S13_V2'
                              AND id < %s
                            ORDER BY id DESC
                            LIMIT 100
                            """,
                            (last_id,)
                        )
                    rows = cur.fetchall()
                    tasks = [(r[0], r[1], r[2]) for r in rows]
            except Exception as e:
                logger.error(f"Error fetching queue page: {e}")
                break

            if not tasks:
                break

            # Update last_id for keyset pagination
            last_id = tasks[-1][0]

            for _, pid, q_status in tasks:
                # 1. Resolve facts
                facts = self.orchestrator.fetch_procurement_facts(pid)
                if not facts:
                    continue
                source_snapshot_hash = compute_md5(facts)

                # Query all queue rows to aggregate status
                try:
                    with doc_conn.cursor() as cur:
                        cur.execute(
                            "SELECT status FROM document_processing_queue WHERE procurement_id = %s",
                            (pid,)
                        )
                        q_statuses = [r[0] for r in cur.fetchall()]
                except Exception as e:
                    logger.error(f"Error fetching queue rows for procurement {pid}: {e}")
                    continue

                is_terminal = True
                for qs in q_statuses:
                    if qs in ("PENDING", "RUNNING", "RETRY"):
                        is_terminal = False
                        break
                if not is_terminal:
                    # Skip if any document processing is still pending/running/retry
                    continue

                # 2. Fetch docs and evidence
                docs, doc_set_hash = self.orchestrator.fetch_document_research_summary(pid)
                evidence = self.orchestrator.fetch_document_evidence(pid)
                evidence_hash = compute_md5(evidence)

                # 3. Aggregate factual queue status before routing using canonical document count
                source_table = facts.get("source_table")
                source_id = facts.get("source_id")
                contract_number = facts.get("contract_number")
                canonical_doc_count = count_document_links(
                    source_table=source_table,
                    source_id=source_id,
                    contract_number=contract_number
                )

                if canonical_doc_count == 0:
                    effective_status = "NO_LINKS"
                else:
                    if not docs:
                        # Canonical docs exist but processing records missing: NOT terminal/ready!
                        continue
                    
                    all_failed = True
                    for d in docs:
                        if d.get("research_state") not in ("DOWNLOAD_FAILED", "PARSE_FAILED", "UNREADABLE", "UNSUPPORTED_FORMAT"):
                            all_failed = False
                            break
                    if all_failed:
                        effective_status = "FAILED"
                    else:
                        effective_status = "COMPLETED"

                # 4. Check versioned trace status using full identity
                traces = self.crm_db.execute_query(
                    """
                    SELECT id, attempt_count, consensus_state, research_completeness
                    FROM crm_v3_autonomous_analysis_traces
                    WHERE procurement_id = %s
                      AND source_snapshot_hash = %s
                      AND document_set_hash = %s
                      AND extracted_evidence_hash = %s
                      AND registry_hash = %s
                      AND hunter_prompt_version = %s
                      AND auditor_prompt_version = %s
                      AND model_version = %s
                    ORDER BY id DESC LIMIT 1
                    """,
                    (
                        pid,
                        source_snapshot_hash,
                        doc_set_hash,
                        evidence_hash,
                        reg_hash,
                        HUNTER_PROMPT_VERSION,
                        AUDITOR_PROMPT_VERSION,
                        model_version,
                    )
                )
                trace = traces[0] if traces else None

                if not trace:
                    if effective_status == "COMPLETED":
                        # Check actual LLM attempts limit
                        existing_traces = self.crm_db.execute_query(
                            """
                            SELECT MAX(attempt_count) as max_attempts
                            FROM crm_v3_autonomous_analysis_traces
                            WHERE procurement_id = %s
                              AND research_completeness IN ('COMPLETE', 'PARTIAL')
                            """,
                            (pid,)
                        )
                        existing_trace = existing_traces[0] if existing_traces else None
                        attempts = (existing_trace["max_attempts"] or 0) if existing_trace else 0
                        if attempts >= 3:
                            logger.debug(f"Procurement {pid} exceeded maximum actual LLM attempts ({attempts}). Skipping.")
                            continue
                    picked_task = (pid, effective_status)
                    break
                else:
                    if trace["consensus_state"] == "FAILED_PROCESSING":
                        if trace["research_completeness"] == "FAILED":
                            # Document failure terminal, do NOT retry if hashes match
                            continue
                        # LLM failure, check actual LLM attempts count
                        existing_traces = self.crm_db.execute_query(
                            """
                            SELECT MAX(attempt_count) as max_attempts
                            FROM crm_v3_autonomous_analysis_traces
                            WHERE procurement_id = %s
                              AND research_completeness IN ('COMPLETE', 'PARTIAL')
                            """,
                            (pid,)
                        )
                        existing_trace = existing_traces[0] if existing_traces else None
                        attempts = (existing_trace["max_attempts"] or 0) if existing_trace else 0
                        if attempts < 3:
                            picked_task = (pid, effective_status)
                            logger.info(f"Retrying failed procurement {pid} (previous actual LLM attempts: {attempts})")
                            break
                        else:
                            logger.debug(f"Procurement {pid} exceeded maximum actual LLM retry attempts ({attempts}). Skipping.")

            if picked_task is not None:
                break

        doc_conn.close()

        if picked_task is None:
            return 0

        procurement_id, effective_status = picked_task
        logger.info(f"Picked up procurement {procurement_id} with effective status {effective_status} for autonomous processing...")

        try:
            if effective_status == "COMPLETED":
                # Load experience priors context
                priors_text = "EXPERIENCE_PRIORS_TO_HUNTER=DISABLED"

                # Run the Hunter-Auditor learning loop
                result = self.orchestrator.run_learning_loop(procurement_id, priors_text)
                logger.info(f"Successfully processed procurement {procurement_id}. Consensus: {result['consensus_state']}")
            elif effective_status == "NO_LINKS":
                # Save trace with research_completeness = 'NO_DOCUMENTS' and consensus_state = 'NO_DOCUMENTS'
                # Do NOT run LLM inference.
                self.orchestrator.save_terminal_trace(
                    procurement_id=procurement_id,
                    consensus_state="NO_DOCUMENTS",
                    research_completeness="NO_DOCUMENTS"
                )
                logger.info(f"Saved terminal trace for procurement {procurement_id} as NO_DOCUMENTS")
            elif effective_status == "FAILED":
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
            # Worker does NOT write duplicate traces here anymore.
            # Failure persistence is handled entirely inside run_learning_loop().
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
