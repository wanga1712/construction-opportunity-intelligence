"""Factual Procurement Feeder into document_processing_queue.

Ensures continuous feeder capability with watermark control, generation-aware admission,
and candidate advancement truth via keyset pagination.
"""

from datetime import datetime, timezone
import hashlib, json, os, psycopg2, psycopg2.extras
from typing import Any, Dict, List, Optional, Tuple

from src.services.commercial_routing_v3.card_research_state import (
    compute_research_generation_hash,
)
from src.services.commercial_routing_v3.document_links import resolve_document_links
from src.services.commercial_routing_v3.submission_window import actionable_submission_sql

PIPELINE_GENERATION = "S13_V2"
LOW_WATERMARK = 50
HIGH_WATERMARK = 200
FEED_BATCH_SIZE = 25


def _get_doc_db_conn():
    from dotenv import load_dotenv
    load_dotenv("/opt/CRM_Streamlit/.env")
    dsn = {
        "host": os.getenv("S13_DOCUMENT_DB_HOST") if os.getenv("S13_DOCUMENT_DB_HOST") not in (None, "", "S7") else "127.0.0.1",
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT") or os.getenv("CRM_DB_PORT") or "5432"),
        "dbname": "document_intelligence",
        "user": os.getenv("CRM_DB_USER") or "crm_app",
        "password": os.getenv("CRM_DB_PASSWORD") or "",
    }
    return psycopg2.connect(**dsn)


def compute_md5(data: Any) -> str:
    s = json.dumps(data, sort_keys=True, default=str)
    return hashlib.md5(s.encode("utf-8")).hexdigest()


class FactualFeeder:
    """Headless feeder that admits procurements into document_processing_queue based on factual procurement data."""

    def __init__(self, crm_db: Any) -> None:
        self.crm_db = crm_db

    def admit_procurement(
        self,
        procurement_id: int,
        source_table: str,
        source_id: int,
        contract_number: Optional[str] = None,
        queue_lane: str = "crm_active_hot",
        priority_score: int = 50,
        canonical_links: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[Optional[int], bool]:
        """Admit single procurement into document_processing_queue with durable research generation hash.

        Returns tuple of (queue_id, is_newly_created).
        """
        if canonical_links is None:
            try:
                doc_res = resolve_document_links(
                    source_table=source_table or "",
                    source_id=source_id,
                    contract_number=contract_number or "",
                )
                canonical_links = doc_res.get("links") or []
            except Exception:
                canonical_links = []

        gen_hash = compute_research_generation_hash(procurement_id, canonical_links, PIPELINE_GENERATION)

        conn = _get_doc_db_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, status, research_generation_hash
                    FROM document_processing_queue
                    WHERE procurement_id = %s
                      AND pipeline_generation = %s
                      AND research_generation_hash = %s
                    ORDER BY id DESC LIMIT 1
                    """,
                    (procurement_id, PIPELINE_GENERATION, gen_hash),
                )
                existing = cur.fetchone()
                if existing:
                    return existing["id"], False

                cur.execute(
                    """
                    INSERT INTO document_processing_queue (
                        procurement_id, source_table, source_id, contract_number,
                        research_action, queue_lane, priority_score, status,
                        pipeline_generation, research_generation_hash, created_at
                    ) VALUES (%s, %s, %s, %s, 'FULL_RESEARCH', %s, %s, 'PENDING', %s, %s, NOW())
                    RETURNING id
                    """,
                    (
                        procurement_id,
                        source_table,
                        source_id,
                        contract_number,
                        queue_lane,
                        priority_score,
                        PIPELINE_GENERATION,
                        gen_hash,
                    ),
                )
                q_id = cur.fetchone()["id"]
                conn.commit()
                return q_id, True
        finally:
            conn.close()

    def get_pending_queue_depth(self) -> int:
        """Get current count of pending/running tasks in document_processing_queue."""
        conn = _get_doc_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM document_processing_queue WHERE status IN ('PENDING', 'PROCESSING', 'RUNNING', 'RETRY') AND pipeline_generation = %s",
                    (PIPELINE_GENERATION,),
                )
                return cur.fetchone()[0]
        finally:
            conn.close()

    def run_feeder_cycle(self, max_pages: int = 10) -> Tuple[int, int, int]:
        """Continuous watermark refill cycle with keyset pagination advancing past already enqueued procurements.

        Returns tuple: (scanned_count, newly_admitted_count, last_scanned_id).
        """
        depth = self.get_pending_queue_depth()
        if depth >= LOW_WATERMARK:
            return 0, 0, 0

        target_refill = min(HIGH_WATERMARK - depth, FEED_BATCH_SIZE)
        pred = f"p.crm_stage = 'torgi' AND p.award_status = 'submission_open' AND {actionable_submission_sql('p')}"

        last_seen_id = None
        total_scanned = 0
        admitted_new = 0

        for _ in range(max_pages):
            if admitted_new >= target_refill:
                break

            where_clause = pred
            params = [FEED_BATCH_SIZE * 2]
            if last_seen_id is not None:
                where_clause += " AND p.id < %s"
                params = [last_seen_id, FEED_BATCH_SIZE * 2]

            rows = self.crm_db.execute_query(
                f"""
                SELECT p.id, p.source_table, p.source_id, p.contract_number
                FROM crm_procurements p
                WHERE {where_clause}
                ORDER BY p.id DESC
                LIMIT %s
                """,
                params,
            ) or []

            if not rows:
                break

            total_scanned += len(rows)
            last_seen_id = rows[-1]["id"]

            for r in rows:
                if admitted_new >= target_refill:
                    break
                qid, created_new = self.admit_procurement(
                    procurement_id=r["id"],
                    source_table=r["source_table"],
                    source_id=r["source_id"],
                    contract_number=r.get("contract_number"),
                )
                if created_new:
                    admitted_new += 1

        return total_scanned, admitted_new, last_seen_id or 0


    def run_forever(self, sleep_seconds: int = 10) -> None:
        """Continuous production feeder loop."""
        import signal, time, logging
        logger = logging.getLogger("commercial_routing_v3.factual_feeder")
        logger.info("Factual procurement feeder service started.")
        running = [True]

        def _sig_handler(signum, frame):
            logger.info(f"Received signal {signum}, stopping feeder...")
            running[0] = False

        signal.signal(signal.SIGINT, _sig_handler)
        signal.signal(signal.SIGTERM, _sig_handler)

        while running[0]:
            try:
                depth_before = self.get_pending_queue_depth()
                scanned, newly_admitted, last_id = self.run_feeder_cycle()
                depth_after = self.get_pending_queue_depth()
                logger.info(
                    f"Feeder cycle: depth_before={depth_before}, scanned={scanned}, "
                    f"newly_admitted={newly_admitted}, last_scanned_id={last_id}, depth_after={depth_after}"
                )
            except Exception as exc:
                logger.error(f"Error in feeder loop: {exc}", exc_info=True)

            for _ in range(sleep_seconds):
                if not running[0]:
                    break
                time.sleep(1)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    from src.services.db_bootstrap import connect_databases
    _, _, crm_db, _ = connect_databases()
    feeder = FactualFeeder(crm_db)
    feeder.run_forever()
