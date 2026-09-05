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
    """Queue backed by local document_intelligence DB on SERVER 13.

    When MODEL_QUEUE_PRIORITY_ENABLED=1, claim_batch uses a two-phase
    approach: SQL locks a candidate pool, Python DWRR selects from it,
    then SQL claims only the selected IDs — all within one transaction.
    """

    def __init__(self, dsn: Dict[str, Any]) -> None:
        self._dsn = dsn
        self._conn: Optional[psycopg2.extensions.connection] = None
        self._dwrr_policy: Optional[Any] = None  # lazy init

    def _get_conn(self) -> psycopg2.extensions.connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self._dsn)
            self._conn.autocommit = False
        return self._conn

    def _get_dwrr_policy(self):
        """Lazy-init shared DWRR policy (survives across claim calls)."""
        if self._dwrr_policy is None:
            from src.services.dwrr_claim_policy import DWRRClaimPolicy
            self._dwrr_policy = DWRRClaimPolicy()
        return self._dwrr_policy

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

        model_priority_enabled = os.getenv("MODEL_QUEUE_PRIORITY_ENABLED", "0").lower() in ("1", "true", "yes", "on")

        if not model_priority_enabled:
            # Legacy path: simple SQL ORDER BY, no DWRR
            order_by_sql = f"""
                {LANE_RANK_SQL} ASC,
                q.priority_score DESC,
                q.id ASC
            """
            sql = f"""
                UPDATE document_processing_queue
                   SET status = 'PROCESSING',
                       worker_id = %s,
                       started_at = NOW(),
                       attempt_count = attempt_count + 1
                 WHERE id IN (
                    SELECT q.id
                      FROM document_processing_queue q
                     WHERE q.status IN ('PENDING', 'PRE_RESEARCH_WAITING')
                       {lane_filter}
                     ORDER BY {order_by_sql}
                     LIMIT %s
                     FOR UPDATE SKIP LOCKED
                 )
             RETURNING id, procurement_id, source_table, source_id,
                       contract_number, assessment_id, category_codes,
                       category_context, candidate_level, candidate_score,
                       research_action, research_depth, queue_lane, pipeline_generation,
                       research_prior_model, research_prior_version, research_prior_score,
                       research_prior_percentile, research_prior_band, research_prior_effective_score
            """
            params = [worker_id] + lane_params + [batch_size]
            conn = self._get_conn()
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
            conn.commit()
            return [dict(r) for r in rows]

        # ── Two-phase weighted claim with per-band diverse pool ──────────
        from src.services.dwrr_claim_policy import pool_size

        candidate_limit = pool_size(batch_size)
        per_band_limit = max(candidate_limit, 20)

        _COLS = """q.id, q.procurement_id, q.source_table, q.source_id,
                   q.contract_number, q.assessment_id, q.category_codes,
                   q.category_context, q.candidate_level, q.candidate_score,
                   q.research_action, q.research_depth, q.queue_lane, q.pipeline_generation,
                   q.research_prior_model, q.research_prior_version, q.research_prior_score,
                   q.research_prior_percentile, q.research_prior_band, q.research_prior_effective_score,
                   q.procurement_scope_type, q.normalized_nmck_rub"""

        _ORDER = f"""{LANE_RANK_SQL} ASC,
            COALESCE(q.research_prior_effective_score, q.priority_score) DESC,
            q.research_prior_score DESC NULLS LAST,
            q.id ASC"""

        # Phase A: Lock candidate pool — effective-band UNION ALL with subpool partitioning.
        # 1. Model GOLD subpool (raw GOLD)
        # 2. Direct Goods Override subpool (DIRECT_GOODS >= 50k, raw band != GOLD)
        # 3. SILVER, BRONZE, WOOD, UNSCORED subqueries (excluding DIRECT_GOODS >= 50k)
        union_parts = []
        union_params: list = []

        # Model GOLD
        union_parts.append(f"""(
            SELECT {_COLS}
              FROM document_processing_queue q
             WHERE q.status IN ('PENDING', 'PRE_RESEARCH_WAITING')
               AND q.research_prior_band = 'GOLD'{lane_filter}
             ORDER BY {_ORDER} LIMIT %s FOR UPDATE SKIP LOCKED)""")
        union_params.extend(lane_params + [per_band_limit])

        # Direct Goods Override to GOLD (non-model-gold)
        union_parts.append(f"""(
            SELECT {_COLS}
              FROM document_processing_queue q
             WHERE q.status IN ('PENDING', 'PRE_RESEARCH_WAITING')
               AND q.procurement_scope_type = 'DIRECT_GOODS'
               AND COALESCE(q.normalized_nmck_rub, 0) >= 50000
               AND (q.research_prior_band IS NULL OR q.research_prior_band != 'GOLD'){lane_filter}
             ORDER BY {_ORDER} LIMIT %s FOR UPDATE SKIP LOCKED)""")
        union_params.extend(lane_params + [per_band_limit])

        # Other bands (SILVER, BRONZE, WOOD) excluding DIRECT_GOODS >= 50k
        for bname in ['SILVER', 'BRONZE', 'WOOD']:
            union_parts.append(f"""(
                SELECT {_COLS}
                  FROM document_processing_queue q
                 WHERE q.status IN ('PENDING', 'PRE_RESEARCH_WAITING')
                   AND q.research_prior_band = %s
                   AND NOT (q.procurement_scope_type = 'DIRECT_GOODS' AND COALESCE(q.normalized_nmck_rub, 0) >= 50000){lane_filter}
                 ORDER BY {_ORDER} LIMIT %s FOR UPDATE SKIP LOCKED)""")
            union_params.extend([bname] + lane_params + [per_band_limit])

        # UNSCORED / NULL band excluding DIRECT_GOODS >= 50k
        union_parts.append(f"""(
            SELECT {_COLS}
              FROM document_processing_queue q
             WHERE q.status IN ('PENDING', 'PRE_RESEARCH_WAITING')
               AND (q.research_prior_band IS NULL
                    OR q.research_prior_band NOT IN ('GOLD','SILVER','BRONZE','WOOD'))
               AND NOT (q.procurement_scope_type = 'DIRECT_GOODS' AND COALESCE(q.normalized_nmck_rub, 0) >= 50000){lane_filter}
             ORDER BY {_ORDER} LIMIT %s FOR UPDATE SKIP LOCKED)""")
        union_params.extend(lane_params + [per_band_limit])

        select_sql = " UNION ALL ".join(union_parts)
        select_params = union_params

        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(select_sql, select_params)
                raw_rows = [dict(r) for r in cur.fetchall()]

            # Deduplicate by ID to guarantee POOL_DUPLICATE_IDS = 0
            seen_ids = set()
            pool_rows = []
            for r in raw_rows:
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    pool_rows.append(r)

            if not pool_rows:
                conn.commit()
                return []

            # Phase B: DWRR select
            policy = self._get_dwrr_policy()
            selected_ids = policy.select_from_pool(pool_rows, batch_size)

            if not selected_ids:
                conn.commit()
                return []

            # Phase C: Claim selected IDs
            id_placeholders = ", ".join(["%s"] * len(selected_ids))
            update_sql = f"""
                UPDATE document_processing_queue
                   SET status = 'PROCESSING',
                       worker_id = %s,
                       started_at = NOW(),
                       attempt_count = attempt_count + 1
                 WHERE id IN ({id_placeholders})
             RETURNING id, procurement_id, source_table, source_id,
                       contract_number, assessment_id, category_codes,
                       category_context, candidate_level, candidate_score,
                       research_action, research_depth, queue_lane, pipeline_generation,
                       research_prior_model, research_prior_version, research_prior_score,
                       research_prior_percentile, research_prior_band, research_prior_effective_score
            """
            update_params = [worker_id] + selected_ids
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(update_sql, update_params)
                claimed_rows = [dict(r) for r in cur.fetchall()]

            # Phase D: Commit (releases locks on unclaimed pool rows)
            conn.commit()
            return claimed_rows
        except Exception:
            conn.rollback()
            raise

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
