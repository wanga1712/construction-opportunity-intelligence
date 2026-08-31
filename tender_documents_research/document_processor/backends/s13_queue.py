"""
document_processor/backends/s13_queue.py

S13V2 queue backend: claim/mark tasks in local document_intelligence DB.
All credentials from env (S13_DOCUMENT_DB_* vars).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence

import psycopg2
import psycopg2.extras

PIPELINE_S13V2 = "S13_V2"

_LANE_RANK_SQL = """
    CASE q.queue_lane
        WHEN 'crm_active_hot'     THEN 1
        WHEN 'open_active'        THEN 2
        WHEN 'awarded_recent'     THEN 3
        WHEN 'historical_awarded' THEN 4
        ELSE 5
    END
"""


class S13V2QueueBackend:
    """
    Claim tasks from document_intelligence.document_processing_queue.
    Stateful persistent psycopg2 connection (lazy init).
    """

    def __init__(self, dsn: Dict[str, Any]) -> None:
        self._dsn = dsn
        self._conn: Optional[psycopg2.extensions.connection] = None

    def _get_conn(self) -> psycopg2.extensions.connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self._dsn)
            self._conn.autocommit = False
        return self._conn

    def verify_connection(self) -> None:
        """Raise if DB unreachable. Called at startup (fail-fast)."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")

    def pipeline_generation(self) -> str:
        return PIPELINE_S13V2

    def claim_batch(
        self,
        worker_id: int,
        batch_size: int,
        queue_lanes: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        lane_filter = ""
        lane_params: List[Any] = []
        if queue_lanes:
            placeholders = ", ".join(["%s"] * len(queue_lanes))
            lane_filter = f" AND q.queue_lane IN ({placeholders})"
            lane_params = list(queue_lanes)

        sql = f"""
            UPDATE document_processing_queue
               SET status     = 'PROCESSING',
                   worker_id  = %s,
                   started_at = NOW()
             WHERE id IN (
                 SELECT q.id
                   FROM document_processing_queue q
                  WHERE q.status = 'PENDING'
                    AND (q.next_attempt_at IS NULL OR q.next_attempt_at <= NOW())
                    {lane_filter}
                  ORDER BY {_LANE_RANK_SQL} ASC,
                           q.priority_score DESC,
                           q.id ASC
                  LIMIT %s
                  FOR UPDATE SKIP LOCKED
             )
         RETURNING
             id, procurement_id, source_table, source_id,
             contract_number, queue_lane, pipeline_generation,
             research_action, research_depth, category_codes
        """
        params = [worker_id] + lane_params + [batch_size]
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        conn.commit()
        return [dict(r) for r in rows]

    def mark_completed(self, task_id: int) -> None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE document_processing_queue"
                " SET status='COMPLETED', completed_at=NOW() WHERE id=%s",
                (task_id,),
            )
        conn.commit()

    def mark_failed(self, task_id: int, error: str) -> None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE document_processing_queue"
                " SET status='FAILED', last_error=%s WHERE id=%s",
                (error[:2000], task_id),
            )
        conn.commit()

    def mark_no_links(self, task_id: int, reason: str) -> None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE document_processing_queue"
                " SET status='NO_LINKS', last_error=%s, completed_at=NOW()"
                " WHERE id=%s",
                (reason[:2000], task_id),
            )
        conn.commit()

    def mark_pending(self, task_id: int) -> None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE document_processing_queue"
                " SET status='PENDING', worker_id=NULL, started_at=NULL WHERE id=%s",
                (task_id,),
            )
        conn.commit()

    def reset_stale(self, stale_minutes: int, worker_id: int) -> int:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE document_processing_queue
                      SET status='PENDING', worker_id=NULL, started_at=NULL,
                          last_error='reset_stale'
                    WHERE status='PROCESSING'
                      AND worker_id = %s
                      AND started_at < NOW() - (%s || ' minutes')::interval
                RETURNING id""",
                (worker_id, stale_minutes),
            )
            count = cur.rowcount
        conn.commit()
        return count
