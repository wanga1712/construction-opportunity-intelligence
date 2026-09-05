"""
document_processor/backends/queue_repository.py

Defines the QueueRepository interface and its implementations:
- LegacyQueueRepository (tender_monitor, S7)
- S13V2QueueRepository (document_intelligence, S13)
"""
import abc
import os
from typing import Any, Dict, List, Optional, Sequence
import psycopg2
import psycopg2.extras
from database_work.database_connection import DatabaseManager

PIPELINE_S13V2 = "S13_V2"

class QueueRepository(abc.ABC):
    @abc.abstractmethod
    def claim_batch(self, worker_id: int, batch_size: int, force_contract: Optional[str] = None, force_table: Optional[str] = None, queue_lanes: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        pass

    @abc.abstractmethod
    def mark_completed(self, task_id: int) -> None:
        pass

    @abc.abstractmethod
    def mark_failed(self, task_id: int, error: str) -> None:
        pass

    @abc.abstractmethod
    def mark_no_links(self, task_id: int, reason: str) -> None:
        pass

    @abc.abstractmethod
    def mark_pending(self, task_id: int, message: str = "") -> None:
        pass

    @abc.abstractmethod
    def reset_stale(self, stale_minutes: int, worker_id: int) -> int:
        pass

    @abc.abstractmethod
    def requeue_error_tasks(self) -> int:
        pass

    @abc.abstractmethod
    def requeue_no_links_with_links(self) -> int:
        pass

    @abc.abstractmethod
    def cleanup_previous_run_data(self) -> None:
        pass

    @abc.abstractmethod
    def get_queue_stats(self, worker_id: int) -> List[Dict[str, Any]]:
        pass

    @abc.abstractmethod
    def get_stale_count(self, stale_minutes: int) -> int:
        pass


class S13V2QueueRepository(QueueRepository):
    """
    Claim tasks from document_intelligence.document_processing_queue.
    Stateful persistent psycopg2 connection (lazy init).

    When MODEL_QUEUE_PRIORITY_ENABLED=1, claim_batch uses a two-phase
    approach: SQL locks a candidate pool, Python DWRR selects from it,
    then SQL claims only the selected IDs — all within one transaction.
    """
    def __init__(self, dsn: Dict[str, Any], pipeline_generation: str = PIPELINE_S13V2) -> None:
        self._dsn = dsn
        self._conn: Optional[psycopg2.extensions.connection] = None
        self._pipeline_generation = pipeline_generation
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

    def pipeline_generation(self) -> str:
        return self._pipeline_generation

    def claim_batch(
        self,
        worker_id: int,
        batch_size: int,
        force_contract: Optional[str] = None,
        force_table: Optional[str] = None,
        queue_lanes: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        lane_filter = ""
        lane_params: List[Any] = []
        if queue_lanes:
            placeholders = ", ".join(["%s"] * len(queue_lanes))
            lane_filter = f" AND q.queue_lane IN ({placeholders})"
            lane_params = list(queue_lanes)

        if force_contract:
            lane_filter += " AND q.contract_number = %s"
            lane_params.append(force_contract)
        if force_table:
            lane_filter += " AND q.source_table = %s"
            lane_params.append(force_table)

        _LANE_RANK_SQL = """
            CASE q.queue_lane
                WHEN 'crm_active_hot'     THEN 1
                WHEN 'open_active'        THEN 2
                WHEN 'awarded_recent'     THEN 3
                WHEN 'historical_awarded' THEN 4
                ELSE 5
            END
        """

        model_priority_enabled = os.getenv("MODEL_QUEUE_PRIORITY_ENABLED", "0").lower() in ("1", "true", "yes", "on")

        if not model_priority_enabled:
            # Legacy path: simple SQL ORDER BY, no DWRR
            order_clause = f"""
                {_LANE_RANK_SQL} ASC,
                q.priority_score DESC,
                q.id ASC
            """
            sql = f"""
                UPDATE document_processing_queue
                   SET status     = 'PROCESSING',
                       worker_id  = %s,
                       started_at = NOW()
                 WHERE id IN (
                      SELECT q.id
                        FROM document_processing_queue q
                       WHERE q.status IN ('PENDING', 'PRE_RESEARCH_WAITING')
                         AND (q.pipeline_generation = %s OR q.pipeline_generation IS NULL)
                         {lane_filter}
                       ORDER BY {order_clause}
                      LIMIT %s
                      FOR UPDATE SKIP LOCKED
                 )
             RETURNING
                 id, procurement_id, source_table, source_id,
                 contract_number, queue_lane, pipeline_generation,
                 research_action, research_depth, category_codes,
                 research_prior_model, research_prior_version, research_prior_score,
                 research_prior_percentile, research_prior_band, research_prior_effective_score
            """
            params = [worker_id, self.pipeline_generation()] + lane_params + [batch_size]
            conn = self._get_conn()
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
            conn.commit()
            return self._adapt_rows(rows)

        # ── Two-phase weighted claim with per-band diverse pool ──────────
        from src.services.dwrr_claim_policy import pool_size

        candidate_limit = pool_size(batch_size)
        per_band_limit = max(candidate_limit, 20)

        _COLS = """q.id, q.procurement_id, q.source_table, q.source_id,
                   q.contract_number, q.queue_lane, q.pipeline_generation,
                   q.research_action, q.research_depth, q.category_codes,
                   q.research_prior_model, q.research_prior_version, q.research_prior_score,
                   q.research_prior_percentile, q.research_prior_band, q.research_prior_effective_score"""

        _ORDER = f"""{_LANE_RANK_SQL} ASC,
            COALESCE(q.research_prior_effective_score, q.priority_score) DESC,
            q.research_prior_score DESC NULLS LAST,
            q.id ASC"""

        _GEN_FILTER = " AND (q.pipeline_generation = %s OR q.pipeline_generation IS NULL)"

        # Phase A: Lock candidate pool — per-band UNION ALL.
        band_names = ['GOLD', 'SILVER', 'BRONZE', 'WOOD']
        union_parts = []
        union_params: list = []
        for bname in band_names:
            union_parts.append(f"""(
                SELECT {_COLS}
                  FROM document_processing_queue q
                 WHERE q.status IN ('PENDING', 'PRE_RESEARCH_WAITING')
                   AND q.research_prior_band = %s{_GEN_FILTER}{lane_filter}
                 ORDER BY {_ORDER} LIMIT %s FOR UPDATE SKIP LOCKED)""")
            union_params.extend([bname, self.pipeline_generation()] + lane_params + [per_band_limit])

        # UNSCORED / NULL band
        union_parts.append(f"""(
            SELECT {_COLS}
              FROM document_processing_queue q
             WHERE q.status IN ('PENDING', 'PRE_RESEARCH_WAITING')
               AND (q.research_prior_band IS NULL
                    OR q.research_prior_band NOT IN ('GOLD','SILVER','BRONZE','WOOD')){_GEN_FILTER}{lane_filter}
             ORDER BY {_ORDER} LIMIT %s FOR UPDATE SKIP LOCKED)""")
        union_params.extend([self.pipeline_generation()] + lane_params + [per_band_limit])

        select_sql = " UNION ALL ".join(union_parts)
        select_params = union_params

        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(select_sql, select_params)
                pool_rows = [dict(r) for r in cur.fetchall()]

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
                   SET status     = 'PROCESSING',
                       worker_id  = %s,
                       started_at = NOW()
                 WHERE id IN ({id_placeholders})
             RETURNING
                 id, procurement_id, source_table, source_id,
                 contract_number, queue_lane, pipeline_generation,
                 research_action, research_depth, category_codes,
                 research_prior_model, research_prior_version, research_prior_score,
                 research_prior_percentile, research_prior_band, research_prior_effective_score
            """
            update_params = [worker_id] + selected_ids
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(update_sql, update_params)
                claimed_rows = cur.fetchall()

            # Phase D: Commit (releases locks on unclaimed pool rows)
            conn.commit()
            return self._adapt_rows(claimed_rows)
        except Exception:
            conn.rollback()
            raise

    @staticmethod
    def _adapt_rows(rows) -> List[Dict[str, Any]]:
        """Adapt DB rows to legacy-compatible dict format."""
        res = []
        for r in rows:
            d = dict(r)
            d["contract_reg_number"] = d["contract_number"]
            d["table_source"] = d["source_table"]
            d["priority_class"] = 1  # Dummy
            d["priority_score"] = 0  # Dummy
            res.append(d)
        return res

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
                (error[:2000] if error else None, task_id),
            )
        conn.commit()

    def mark_no_links(self, task_id: int, reason: str) -> None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE document_processing_queue"
                " SET status='NO_LINKS', last_error=%s, completed_at=NOW()"
                " WHERE id=%s",
                (reason[:2000] if reason else None, task_id),
            )
        conn.commit()

    def mark_pending(self, task_id: int, message: str = "") -> None:
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
                      AND (worker_id = %s OR started_at < NOW() - (%s || ' minutes')::interval)
                RETURNING id""",
                (worker_id, str(stale_minutes)),
            )
            count = cur.rowcount
        conn.commit()
        return count

    def requeue_error_tasks(self) -> int:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE document_processing_queue
                      SET status='PENDING', worker_id=NULL, started_at=NULL
                    WHERE status='FAILED'
                RETURNING id"""
            )
            count = cur.rowcount
        conn.commit()
        return count

    def requeue_no_links_with_links(self) -> int:
        # S13_V2 currently doesn't manage no_links requeue logic this way,
        # or it could be implemented later.
        return 0

    def cleanup_previous_run_data(self) -> None:
        pass # Not applicable for S13_V2 local DB

    def get_queue_stats(self, worker_id: int) -> List[Dict[str, Any]]:
        # Dummy stats or actual local stats
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT status, COUNT(*) as count
                FROM document_processing_queue
                GROUP BY status
            """)
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    def get_stale_count(self, stale_minutes: int) -> int:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM document_processing_queue
                WHERE status='PROCESSING' AND started_at < NOW() - (%s || ' minutes')::interval
            """, (str(stale_minutes),))
            row = cur.fetchone()
        return row[0] if row else 0


class LegacyQueueRepository(QueueRepository):
    """
    Legacy queue operations in tender_monitor (S7).
    """
    def __init__(self, db: DatabaseManager, db_alias: str = "tender_monitor") -> None:
        self.db = db
        self.db_alias = db_alias

    def claim_batch(
        self,
        worker_id: int,
        batch_size: int,
        force_contract: Optional[str] = None,
        force_table: Optional[str] = None,
        queue_lanes: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        where_extra = ""
        extra_params = []
        if force_contract:
            where_extra += " AND contract_reg_number = %s"
            extra_params.append(force_contract)
        if force_table:
            where_extra += " AND table_source = %s"
            extra_params.append(force_table)

        # We also need the table_source filtering from allowed sources.
        # But wait, QueueManager does that before calling claim.
        # It's better if QueueManager passes where_extra and extra_params down,
        # or we just rely on the existing queue_claim.py

        from document_processor.queue_claim import claim_batch_ids
        from document_processor.queue_priority import QueuePriorityPolicy
        priority = QueuePriorityPolicy()

        rows = claim_batch_ids(
            db_execute=lambda q, p=None, fetch=True: self.db.execute_query(self.db_alias, q, p, fetch=fetch),
            worker_id=worker_id,
            batch_size=batch_size,
            priority_case=priority.sql_order_case(),
            where_extra=where_extra,
            extra_params=extra_params,
            queue_lanes=queue_lanes,
        )
        result = []
        for row in rows:
            result.append({
                "id":                  row[0],
                "contract_reg_number": row[1],
                "table_source":        row[2],
                "queue_lane":          row[3] if len(row) > 3 else None,
                "priority_class":      row[4] if len(row) > 4 else None,
                "priority_score":      row[5] if len(row) > 5 else None,
            })
        return result

    def mark_completed(self, task_id: int) -> None:
        sql = "UPDATE document_processing_queue SET status = 'completed', completed_at = NOW() WHERE id = %s"
        self.db.execute_query(self.db_alias, sql, (task_id,))

    def mark_failed(self, task_id: int, error: str) -> None:
        sql = "UPDATE document_processing_queue SET status = 'error', error_message = %s, completed_at = NOW() WHERE id = %s"
        self.db.execute_query(self.db_alias, sql, (error, task_id))

    def mark_no_links(self, task_id: int, reason: str) -> None:
        sql = "UPDATE document_processing_queue SET status = 'no_links', worker_id = NULL, started_at = NULL, completed_at = NOW(), error_message = %s WHERE id = %s"
        self.db.execute_query(self.db_alias, sql, (reason, task_id))

    def mark_pending(self, task_id: int, message: str = "") -> None:
        sql = "UPDATE document_processing_queue SET status = 'pending', worker_id = NULL, started_at = NULL, error_message = %s WHERE id = %s"
        self.db.execute_query(self.db_alias, sql, (message or None, task_id))

    def reset_stale(self, stale_minutes: int, worker_id: int) -> int:
        sql = f"""
            UPDATE document_processing_queue
            SET status = 'pending', worker_id = NULL, started_at = NULL
            WHERE status = 'processing'
              AND (
                    worker_id = %s
                 OR (started_at IS NOT NULL AND started_at < NOW() - INTERVAL '{stale_minutes} minutes')
              )
            RETURNING id
        """
        rows = self.db.execute_query(self.db_alias, sql, (worker_id,), fetch=True) or []
        return len(rows)

    def requeue_error_tasks(self) -> int:
        sql = """
            WITH upd AS (
                UPDATE document_processing_queue
                SET status = 'pending', worker_id = NULL, started_at = NULL
                WHERE status = 'error'
                RETURNING id
            )
            SELECT COUNT(*) FROM upd
        """
        rows = self.db.execute_query(self.db_alias, sql, fetch=True) or []
        return int(rows[0][0]) if rows else 0

    def requeue_no_links_with_links(self) -> int:
        sql = """
            WITH has_links AS (
                SELECT DISTINCT q.id
                FROM document_processing_queue q
                WHERE q.status = 'no_links'
                  AND q.table_source LIKE '%44%'
                  AND (
                    EXISTS (
                        SELECT 1 FROM links_documentation_44_fz l
                        WHERE l.contract_number = q.contract_reg_number
                    )
                    OR EXISTS (
                        SELECT 1 FROM links_documentation_44_fz l
                        WHERE l.contract_id IN (
                            SELECT r.id FROM reestr_contract_44_fz r WHERE r.contract_number = q.contract_reg_number
                            UNION ALL
                            SELECT r.id FROM reestr_contract_44_fz_awarded r WHERE r.contract_number = q.contract_reg_number
                        )
                    )
                  )
            ),
            updated AS (
                UPDATE document_processing_queue
                SET status = 'pending', worker_id = NULL, started_at = NULL, error_message = NULL
                WHERE id IN (SELECT id FROM has_links)
                RETURNING id
            )
            SELECT COUNT(*) FROM updated
        """
        rows = self.db.execute_query(self.db_alias, sql, fetch=True) or []
        return int(rows[0][0]) if rows else 0

    def cleanup_previous_run_data(self) -> None:
        for sql in (
            "DELETE FROM tender_document_match_details",
            "DELETE FROM tender_document_matches",
            "DELETE FROM processed_documents",
            "TRUNCATE TABLE document_processing_queue",
        ):
            try:
                self.db.execute_query(self.db_alias, sql)
            except Exception:
                pass

    def get_queue_stats(self, worker_id: int) -> List[Dict[str, Any]]:
        # In reality DaemonMaintenance doesn't fetch stats this way,
        # but if needed, we return it.
        return []

    def get_stale_count(self, stale_minutes: int) -> int:
        sql = f"""
            SELECT COUNT(*) FROM document_processing_queue
            WHERE status = 'processing'
              AND started_at IS NOT NULL
              AND started_at < NOW() - INTERVAL '{stale_minutes} minutes'
        """
        rows = self.db.execute_query(self.db_alias, sql, fetch=True) or []
        return int(rows[0][0]) if rows else 0

