"""Autonomous worker daemon.

Polls for completed document processing tasks and executes the Hunter-Auditor
LLM analysis loop sequentially to establish product evidence and consensus.
"""
from __future__ import annotations

import logging, os, signal, sys, time
from typing import Any, Dict, List, Optional

from src.services.commercial_routing_v3.autonomous_learning_loop import HunterAuditorOrchestrator
from src.services.commercial_routing_v3.card_research_state import (
    compute_research_generation_hash,
    derive_procurement_research_state,
    PIPELINE_GENERATION,
)
from src.services.commercial_routing_v3.document_links import resolve_document_links

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("autonomous_worker")

class AutonomousWorker:
    """Daemon worker that polls completed document tasks and runs Hunter-Auditor loop."""

    def __init__(self, crm_db: Any, procurement_id_filter: Optional[str] = None) -> None:
        self.crm_db = crm_db
        self.orchestrator = HunterAuditorOrchestrator(crm_db)
        self.running = True
        self.procurement_id_filter = procurement_id_filter

    def stop(self) -> None:
        logger.info("Stopping autonomous worker...")
        self.running = False

    def run_once(self) -> int:
        """Poll and process one pending learning task with explicit generation authority."""
        registry = self.orchestrator.load_active_categories()
        reg_hash = self.orchestrator.compute_registry_hash(registry)
        model_version = "qwen2.5:7b"
        from src.services.commercial_routing_v3.autonomous_learning_loop import (
            HUNTER_PROMPT_VERSION,
            AUDITOR_PROMPT_VERSION,
            compute_md5,
        )

        doc_conn = self.orchestrator._get_doc_conn()
        last_id = None
        picked_task = None

        while self.running:
            tasks = []
            try:
                filter_sql = f" AND {self.procurement_id_filter}" if self.procurement_id_filter else ""
                with doc_conn.cursor() as cur:
                    if last_id is None:
                        cur.execute(
                            f"""
                            SELECT id, procurement_id, pipeline_generation, research_generation_hash, status 
                            FROM document_processing_queue
                            WHERE status IN ('COMPLETED', 'FAILED', 'NO_LINKS')
                              AND pipeline_generation = %s{filter_sql}
                            ORDER BY id DESC
                            LIMIT 100
                            """,
                            (PIPELINE_GENERATION,)
                        )
                    else:
                        cur.execute(
                            f"""
                            SELECT id, procurement_id, pipeline_generation, research_generation_hash, status 
                            FROM document_processing_queue
                            WHERE status IN ('COMPLETED', 'FAILED', 'NO_LINKS')
                              AND pipeline_generation = %s{filter_sql}
                              AND id < %s
                            ORDER BY id DESC
                            LIMIT 100
                            """,
                            (PIPELINE_GENERATION, last_id)
                        )
                    rows = cur.fetchall()
                    tasks = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
            except Exception as e:
                logger.error(f"Error fetching queue page: {e}")
                break

            if not tasks:
                break

            last_id = tasks[-1][0]

            for _, pid, pipe_gen, gen_hash, q_status in tasks:
                facts = self.orchestrator.fetch_procurement_facts(pid)
                if not facts:
                    continue
                source_snapshot_hash = compute_md5(facts)

                # WORKER_QUEUE_STATUS_SCOPED_TO_GENERATION = YES
                try:
                    with doc_conn.cursor() as cur:
                        cur.execute(
                            "SELECT status FROM document_processing_queue WHERE procurement_id = %s AND pipeline_generation = %s AND research_generation_hash = %s",
                            (pid, pipe_gen, gen_hash)
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
                    continue

                # WORKER_USES_SHARED_DOCUMENT_COMPLETENESS_AUTHORITY = YES
                source_table = facts.get("source_table")
                source_id = facts.get("source_id")
                contract_number = facts.get("contract_number")

                try:
                    doc_res = resolve_document_links(source_table=source_table or "", source_id=source_id, contract_number=contract_number or "")
                    canonical_links = doc_res.get("links") or []
                except Exception:
                    canonical_links = []

                if not gen_hash:
                    gen_hash = compute_research_generation_hash(pid, canonical_links, pipe_gen)

                state_info = derive_procurement_research_state(
                    pid,
                    self.crm_db,
                    pipeline_generation=pipe_gen,
                    source_table=source_table,
                    source_id=source_id,
                    contract_number=contract_number,
                    canonical_links=canonical_links,
                )

                doc_state = state_info["research_state"]

                if state_info["documents_discovered"] == 0:
                    effective_status = "NO_LINKS"
                elif doc_state == "FAILED":
                    effective_status = "FAILED"
                elif doc_state in ("EVIDENCE_FOUND", "NO_EVIDENCE", "PARTIAL", "WAITING_RESEARCH"):
                    if state_info["documents_researched"] >= state_info["documents_discovered"] and state_info["documents_discovered"] > 0:
                        effective_status = "COMPLETED"
                    else:
                        continue
                else:
                    continue

                # Check versioned trace status
                docs, doc_set_hash = self.orchestrator.fetch_document_research_summary(pid)
                evidence = self.orchestrator.fetch_document_evidence(pid, pipe_gen, gen_hash)
                evidence_hash = compute_md5(evidence)

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
                    picked_task = (pid, pipe_gen, gen_hash, canonical_links, effective_status)
                    break

            if picked_task is not None:
                break

        doc_conn.close()

        if picked_task is None:
            return 0

        procurement_id, pipe_gen, gen_hash, canonical_links, effective_status = picked_task
        logger.info(f"Picked up procurement {procurement_id} (gen: {gen_hash}) with status {effective_status}")

        try:
            if effective_status == "COMPLETED":
                priors_text = "EXPERIENCE_PRIORS_TO_HUNTER=DISABLED"
                result = self.orchestrator.run_learning_loop(
                    procurement_id,
                    priors_text=priors_text,
                    research_generation_hash=gen_hash,
                    canonical_links=canonical_links,
                )
                logger.info(f"Successfully processed procurement {procurement_id}. Consensus: {result['consensus_state']}")
            elif effective_status == "NO_LINKS":
                self.orchestrator.save_terminal_trace(
                    procurement_id=procurement_id,
                    consensus_state="NO_DOCUMENTS",
                    research_completeness="NO_DOCUMENTS"
                )
            elif effective_status == "FAILED":
                self.orchestrator.save_terminal_trace(
                    procurement_id=procurement_id,
                    consensus_state="FAILED_PROCESSING",
                    research_completeness="FAILED"
                )
            return 1
        except Exception as exc:
            logger.error(f"Error processing procurement {procurement_id}: {exc}", exc_info=True)
            return 1

    def run_forever(self, sleep_seconds: int = 5) -> None:
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
    import signal, logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    from src.services.db_bootstrap import connect_databases
    _, _, crm_db, _ = connect_databases()
    worker = AutonomousWorker(crm_db)

    def sigterm_handler(signum, frame):
        worker.stop()

    signal.signal(signal.SIGINT, sigterm_handler)
    signal.signal(signal.SIGTERM, sigterm_handler)

    worker.run_forever()
