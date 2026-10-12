"""Safe, bounded backfill script for projecting First Pass priorities into document_processing_queue.

Supports --dry-run (default: False when passed --execute).
Strictly updates ONLY pending/waiting tasks for active procurements (crm_stage IN ('torgi', 'submission_open')).
Never touches processing, completed, or failed tasks.
Never creates missing queue rows.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import logging
import os
import sys
import time

sys.path.insert(0, "/opt/CRM_Streamlit")
# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv("/opt/CRM_Streamlit/.env")

import psycopg2
import psycopg2.extras
from psycopg2.extras import RealDictCursor

from src.services.crm_db_runtime import require_crm_db_connect_kwargs
from src.services.first_pass.service import FirstPassService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("backfill_active_queue_priorities")

BATCH_SIZE = 5000


class S13CrmDb:
    def __init__(self):
        kwargs = require_crm_db_connect_kwargs()
        self.conn = psycopg2.connect(**kwargs)

    def execute_query(self, sql, params=None):
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def close(self):
        if self.conn and not self.conn.closed:
            self.conn.close()


def get_doc_db_conn():
    from src.services.commercial_routing_v3.factual_feeder import _get_doc_db_conn
    return _get_doc_db_conn()


def backfill_active_queue_priorities(dry_run: bool = True) -> None:
    start_time = time.time()
    mode_str = "DRY RUN (NO DB MUTATIONS)" if dry_run else "EXECUTE (APPLYING DB MUTATIONS)"
    logger.info("Starting safe First Pass priority backfill [%s]...", mode_str)

    crm_db = S13CrmDb()
    service = FirstPassService(crm_db)

    # 1. Fetch eligible pending/waiting tasks from document_processing_queue
    logger.info("Fetching pending/waiting tasks from document_processing_queue...")
    doc_conn = get_doc_db_conn()
    queue_tasks: list[dict] = []
    try:
        with doc_conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, procurement_id, queue_lane, status, priority_score, candidate_level
                FROM document_processing_queue
                WHERE status IN ('pending', 'PRE_RESEARCH_WAITING')
                ORDER BY id ASC
                """
            )
            queue_tasks = cur.fetchall() or []
    finally:
        doc_conn.close()

    total_queue_tasks = len(queue_tasks)
    logger.info("Found %d pending/waiting tasks in document_processing_queue.", total_queue_tasks)
    if total_queue_tasks == 0:
        logger.info("No pending tasks to backfill.")
        return

    # Map procurement_id -> list of queue_tasks
    proc_to_tasks: dict[int, list[dict]] = {}
    for t in queue_tasks:
        pid = t["procurement_id"]
        if pid:
            proc_to_tasks.setdefault(pid, []).append(t)

    all_pids = list(proc_to_tasks.keys())
    logger.info("Distinct procurement IDs in pending queue: %d", len(all_pids))

    # 2. Filter ONLY procurements where crm_stage IN ('torgi', 'submission_open')
    logger.info("Fetching active stage procurements from CRM...")
    all_active = crm_db.execute_query(
        """
        SELECT id, source_table, source_id, contract_number, okpd_code,
               auction_name, end_date, crm_stage, initial_price, object_type
        FROM crm_procurements
        WHERE crm_stage IN ('torgi', 'submission_open')
        """
    ) or []
    pending_pids_set = set(proc_to_tasks.keys())
    active_procs = [p for p in all_active if p["id"] in pending_pids_set]

    logger.info("Matched active stage procurements: %d", len(active_procs))
    if not active_procs:
        logger.info("No active stage procurements found matching pending queue.")
        return

    # 3. Evaluate First Pass for active procurements
    logger.info("Evaluating First Pass for %d active procurements...", len(active_procs))
    eval_by_pid = service.evaluate_batch(active_procs)

    now = datetime.now(timezone.utc)
    updated_tasks_count = 0
    medal_dist: dict[str, int] = {}
    score_sum = 0
    update_tuples = []

    for p in active_procs:
        pid = p["id"]
        res = eval_by_pid.get(pid)
        if not res:
            continue

        tasks = proc_to_tasks.get(pid, [])
        for t in tasks:
            update_tuples.append((
                res.priority_score,
                res.canonical_preliminary_medal,
                res.canonical_preliminary_score,
                res.object_family,
                t["id"],
            ))
            updated_tasks_count += 1

        medal_dist[res.canonical_preliminary_medal] = medal_dist.get(res.canonical_preliminary_medal, 0) + len(tasks)
        score_sum += (res.priority_score * len(tasks))

    logger.info("Prepared %d queue row updates across %d active procurements.", len(update_tuples), len(active_procs))

    # 4. Execute DB mutations if not dry_run
    if not dry_run and update_tuples:
        doc_conn = get_doc_db_conn()
        try:
            with doc_conn.cursor() as cur:
                psycopg2.extras.execute_batch(
                    cur,
                    """
                    UPDATE document_processing_queue
                    SET priority_score = %s,
                        candidate_level = %s,
                        candidate_score = %s,
                        procurement_scope_type = %s
                    WHERE id = %s
                      AND status IN ('pending', 'PRE_RESEARCH_WAITING')
                    """,
                    update_tuples,
                    page_size=1000,
                )
                doc_conn.commit()
            logger.info("Executed %d database updates successfully.", len(update_tuples))
        finally:
            doc_conn.close()
    crm_db.close()

    elapsed = time.time() - start_time
    avg_score = (score_sum / len(active_procs)) if active_procs else 0.0

    logger.info("=" * 65)
    logger.info("BACKFILL SUMMARY (%s)", "DRY RUN" if dry_run else "EXECUTED")
    logger.info("  Active Procurements Processed: %d", len(active_procs))
    logger.info("  Queue Tasks Targeted: %d", updated_tasks_count)
    logger.info("  Average Priority Score: %.2f", avg_score)
    logger.info("  Medal Distribution: %s", medal_dist)
    logger.info("  Elapsed Time: %.2f seconds", elapsed)
    logger.info("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill active queue priorities with First Pass.")
    parser.add_argument("--execute", action="store_true", help="Execute actual DB update (default is dry-run)")
    args = parser.parse_args()

    backfill_active_queue_priorities(dry_run=not args.execute)
