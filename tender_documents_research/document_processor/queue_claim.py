"""
Queue claim: lane-based ordering.

Lane priority (lower = higher):
  crm_active_hot=1  open_active=2  awarded_recent=3  retry=4  historical_awarded=5

Within a lane: priority_score DESC → submission_end_at ASC → id ASC
"""

from __future__ import annotations

import os
from typing import List, Optional, Sequence, Tuple

LANE_RANK_SQL = """
    CASE q.queue_lane
        WHEN 'crm_active_hot'    THEN 1
        WHEN 'open_active'       THEN 2
        WHEN 'awarded_recent'    THEN 3
        WHEN 'retry'             THEN 4
        WHEN 'historical_awarded' THEN 5
        ELSE 6
    END
"""


def reprocess_enrich_predicate_sql() -> str:
    return "COALESCE(error_message, '') LIKE 'reprocess_enrich:%%'"


def backfill_slots(batch_size: int) -> int:
    try:
        slots = int(os.getenv("BACKFILL_SLOTS", "1"))
    except ValueError:
        slots = 1
    if batch_size <= 1:
        return 0
    return max(0, min(slots, batch_size - 1))


def claim_batch_ids(
    *,
    db_execute,
    worker_id: int,
    batch_size: int,
    priority_case: str,       # kept for API compat, not used in ORDER BY
    where_extra: str,
    extra_params: Sequence[object],
    queue_lanes: Optional[Sequence[str]] = None,
) -> List[Tuple]:
    """
    Claim pending tasks ordered by lane rank → priority_score → deadline.
    queue_lanes restricts which lanes this worker handles.
    """
    slots = backfill_slots(batch_size)
    normal_limit = batch_size - slots
    repr_pred = reprocess_enrich_predicate_sql()

    lane_filter, lane_params = _lane_filter(queue_lanes)

    claimed: List[Tuple] = []

    if normal_limit > 0:
        claimed.extend(_claim(
            db_execute=db_execute,
            worker_id=worker_id,
            limit=normal_limit,
            where_extra=where_extra + f" AND NOT ({repr_pred})" + lane_filter,
            extra_params=list(extra_params) + lane_params,
        ))

    remaining = batch_size - len(claimed)
    if remaining > 0 and slots > 0:
        claimed.extend(_claim(
            db_execute=db_execute,
            worker_id=worker_id,
            limit=remaining,
            where_extra=where_extra + f" AND ({repr_pred})" + lane_filter,
            extra_params=list(extra_params) + lane_params,
        ))

    remaining = batch_size - len(claimed)
    if remaining > 0:
        claimed.extend(_claim(
            db_execute=db_execute,
            worker_id=worker_id,
            limit=remaining,
            where_extra=where_extra + f" AND NOT ({repr_pred})" + lane_filter,
            extra_params=list(extra_params) + lane_params,
        ))

    return claimed


def _lane_filter(lanes: Optional[Sequence[str]]) -> tuple[str, list]:
    if not lanes:
        return "", []
    placeholders = ", ".join(["%s"] * len(lanes))
    return f" AND q.queue_lane IN ({placeholders})", list(lanes)


def _claim(
    *,
    db_execute,
    worker_id: int,
    limit: int,
    where_extra: str,
    extra_params: Sequence[object],
) -> List[Tuple]:
    if limit <= 0:
        return []
    params: List[object] = [worker_id, worker_id, *list(extra_params), limit]
    model_priority_enabled = os.getenv("MODEL_QUEUE_PRIORITY_ENABLED", "0").lower() in ("1", "true", "yes", "on")
    if model_priority_enabled:
        order_by_clause = f"""
            {LANE_RANK_SQL} ASC,
            COALESCE(q.research_prior_effective_score, q.priority_score) DESC,
            q.research_prior_score DESC NULLS LAST,
            q.submission_end_at ASC NULLS LAST,
            q.id ASC
        """
    else:

        order_by_clause = f"""
            {LANE_RANK_SQL} ASC,
            q.priority_score DESC,
            q.submission_end_at ASC NULLS LAST,
            q.id ASC
        """

    sql = f"""
        UPDATE document_processing_queue
        SET status     = 'processing',
            worker_id  = %s,
            started_at = NOW()
        WHERE id IN (
            SELECT q.id
            FROM document_processing_queue q
            WHERE q.status = 'pending'
              AND (q.worker_id IS NULL OR q.worker_id = %s)
              {where_extra}
            ORDER BY
                {order_by_clause}
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        )
        RETURNING id, contract_reg_number, table_source, queue_lane, priority_class, priority_score
    """
    return list(db_execute(sql, tuple(params), fetch=True) or [])
