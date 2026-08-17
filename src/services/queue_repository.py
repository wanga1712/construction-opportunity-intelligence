"""
QueueRepository abstraction for document processing pipeline.

Two backends:
  LegacyQueueRepository  → tender_monitor.document_processing_queue  (SERVER 7)
  S13V2QueueRepository   → document_intelligence.document_processing_queue (SERVER 13 local)

The daemon selects backend via PROCESSING_BACKEND env var.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Sequence

import psycopg2
import psycopg2.extras

PIPELINE_S13V2 = "S13_V2"
PIPELINE_LEGACY = "LEGACY"

# ──────────────────────────────────────────────────────────────────────────────
# Abstract base
# ──────────────────────────────────────────────────────────────────────────────

class QueueRepository(ABC):
    """Interface for queue persistence. Implementations must be thread-safe."""

    @abstractmethod
    def claim_batch(
        self,
        worker_id: int,
        batch_size: int,
        queue_lanes: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Atomically claim pending tasks. Returns claimed rows as dicts."""

    @abstractmethod
    def mark_no_links(self, task_id: int, reason: str) -> None:
        """Mark task as NO_LINKS."""

    @abstractmethod
    def mark_failed(self, task_id: int, error: str, attempt_count: int) -> None:
        """Mark task as FAILED with error detail."""

    @abstractmethod
    def mark_completed(self, task_id: int) -> None:
        """Mark task as COMPLETED."""

    @abstractmethod
    def mark_pending(self, task_id: int) -> None:
        """Return task to PENDING (resume)."""

    @abstractmethod
    def reset_stale_tasks(self, stale_minutes: int, worker_id: int) -> int:
        """Reset stale processing tasks back to PENDING. Returns count."""

    @abstractmethod
    def pipeline_generation(self) -> str:
        """Return the pipeline_generation token for this backend."""


# ──────────────────────────────────────────────────────────────────────────────
# Legacy backend (tender_monitor on SERVER 7)
# ──────────────────────────────────────────────────────────────────────────────

class LegacyQueueRepository(QueueRepository):
    """Delegates to existing DatabaseManager / queue_claim module."""

    def __init__(self, db) -> None:
        self._db = db  # DatabaseManager instance (existing)

    def pipeline_generation(self) -> str:
        return PIPELINE_LEGACY

    def claim_batch(
        self,
        worker_id: int,
        batch_size: int,
        queue_lanes: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        from .queue_manager import QueueManager
        qm = QueueManager(self._db)
        rows = qm.get_next_batch(worker_id, batch_size)
        return rows or []

    def mark_no_links(self, task_id: int, reason: str) -> None:
        from .queue_manager import QueueManager
        QueueManager(self._db).mark_no_links(task_id, reason)

    def mark_failed(self, task_id: int, error: str, attempt_count: int) -> None:
        self._db.execute_query(
            "tender_monitor",
            "UPDATE document_processing_queue SET status='error', last_error=%s"
            " WHERE id=%s",
            (error[:2000], task_id),
        )

    def mark_completed(self, task_id: int) -> None:
        self._db.execute_query(
            "tender_monitor",
            "UPDATE document_processing_queue SET status='completed', completed_at=NOW()"
            " WHERE id=%s",
            (task_id,),
        )

    def mark_pending(self, task_id: int) -> None:
        self._db.execute_query(
            "tender_monitor",
            "UPDATE document_processing_queue"
            " SET status='pending', worker_id=NULL, started_at=NULL WHERE id=%s",
            (task_id,),
        )

    def reset_stale_tasks(self, stale_minutes: int, worker_id: int) -> int:
        from .daemon_maintenance import DaemonMaintenance
        dm = DaemonMaintenance(self._db, worker_id, 0, None)
        dm.reset_stale_tasks()
        return 0


# ──────────────────────────────────────────────────────────────────────────────
# S13_V2 backend (document_intelligence on SERVER 13 local)
# ──────────────────────────────────────────────────────────────────────────────

LANE_RANK_SQL = """
    CASE q.queue_lane
        WHEN 'crm_active_hot'     THEN 1
        WHEN 'open_active'        THEN 2
        WHEN 'awarded_recent'     THEN 3
        WHEN 'historical_awarded' THEN 4
        ELSE 5
    END
"""


class S13V2QueueRepository(QueueRepository):
    """Queue backed by local document_intelligence DB on SERVER 13."""

    def __init__(self, dsn: Dict[str, Any]) -> None:
        self._dsn = dsn
        self._conn: Optional[psycopg2.extensions.connection] = None

    def _get_conn(self) -> psycopg2.extensions.connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self._dsn)
            self._conn.autocommit = False
        return self._conn

    def _execute(self, sql: str, params=None, fetch: bool = False):
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if fetch:
                return cur.fetchall()
        conn.commit()
        return None

    def pipeline_generation(self) -> str:
        return PIPELINE_S13V2

    def claim_batch(
        self,
        worker_id: int,
        batch_size: int,
        queue_lanes: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        lane_filter = ""
        lane_params: list = []
        if queue_lanes:
            placeholders = ", ".join(["%s"] * len(queue_lanes))
            lane_filter = f" AND q.queue_lane IN ({placeholders})"
            lane_params = list(queue_lanes)

        sql = f"""
            UPDATE document_processing_queue
               SET status = 'PROCESSING',
                   worker_id = %s,
                   started_at = NOW(),
                   attempt_count = attempt_count + 1
             WHERE id IN (
                SELECT q.id
                  FROM document_processing_queue q
                 WHERE q.status = 'PENDING'
                   {lane_filter}
                 ORDER BY {LANE_RANK_SQL} ASC,
                          q.priority_score DESC,
                          q.id ASC
                 LIMIT %s
                 FOR UPDATE SKIP LOCKED
             )
         RETURNING id, procurement_id, source_table, source_id,
                   contract_number, assessment_id, category_codes,
                   category_context, candidate_level, candidate_score,
                   research_action, research_depth, queue_lane, pipeline_generation
        """
        params = [worker_id] + lane_params + [batch_size]
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        conn.commit()
        return [dict(r) for r in rows]

    def mark_no_links(self, task_id: int, reason: str) -> None:
        self._execute(
            "UPDATE document_processing_queue"
            " SET status='NO_LINKS', completed_at=NOW(), last_error=%s WHERE id=%s",
            (reason[:2000], task_id),
        )

    def mark_failed(self, task_id: int, error: str, attempt_count: int) -> None:
        self._execute(
            "UPDATE document_processing_queue"
            " SET status='FAILED', last_error=%s, completed_at=NOW() WHERE id=%s",
            (error[:2000], task_id),
        )

    def mark_completed(self, task_id: int) -> None:
        self._execute(
            "UPDATE document_processing_queue"
            " SET status='COMPLETED', completed_at=NOW() WHERE id=%s",
            (task_id,),
        )

    def mark_pending(self, task_id: int) -> None:
        self._execute(
            "UPDATE document_processing_queue"
            " SET status='PENDING', worker_id=NULL, started_at=NULL WHERE id=%s",
            (task_id,),
        )

    def reset_stale_tasks(self, stale_minutes: int, worker_id: int) -> int:
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


# ──────────────────────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────────────────────

def build_queue_repository(backend: str, db) -> QueueRepository:
    """
    backend: 'S13_V2' or 'LEGACY' (default).
    db: DatabaseManager (for legacy) or ignored (S13_V2 reads env directly).
    """
    if backend == PIPELINE_S13V2:
        dsn = {
            "host":     os.getenv("S13_DOCUMENT_DB_HOST", "localhost"),
            "port":     int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
            "dbname":   os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
            "user":     os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
            "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
        }
        return S13V2QueueRepository(dsn)
    return LegacyQueueRepository(db)
