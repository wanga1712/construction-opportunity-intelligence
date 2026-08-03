"""Выбор задач очереди: новые в приоритете, fair-share для backfill."""

from __future__ import annotations

import os
from typing import List, Optional, Sequence, Tuple


def reprocess_enrich_predicate_sql() -> str:
    # %% — экранирование для psycopg2 при наличии params
    return "COALESCE(error_message, '') LIKE 'reprocess_enrich:%%'"


def backfill_slots(batch_size: int) -> int:
    """Сколько слотов батча отдать reprocess_enrich (остальное — обычные pending)."""
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
    priority_case: str,
    where_extra: str,
    extra_params: Sequence[object],
) -> List[Tuple]:
    """
    Забирает pending: сначала обычные (новые/приоритетные),
    затем до backfill_slots() задач reprocess_enrich.
    """
    slots = backfill_slots(batch_size)
    normal_limit = batch_size - slots
    repr_pred = reprocess_enrich_predicate_sql()

    claimed: List[Tuple] = []
    if normal_limit > 0:
        claimed.extend(
            _claim(
                db_execute=db_execute,
                worker_id=worker_id,
                limit=normal_limit,
                priority_case=priority_case,
                where_extra=where_extra + f" AND NOT ({repr_pred})",
                extra_params=extra_params,
            )
        )

    remaining = batch_size - len(claimed)
    if remaining > 0 and slots > 0:
        claimed.extend(
            _claim(
                db_execute=db_execute,
                worker_id=worker_id,
                limit=remaining,
                priority_case=priority_case,
                where_extra=where_extra + f" AND ({repr_pred})",
                extra_params=extra_params,
            )
        )

    # Если reprocess не было — добираем обычными до batch_size
    remaining = batch_size - len(claimed)
    if remaining > 0:
        claimed.extend(
            _claim(
                db_execute=db_execute,
                worker_id=worker_id,
                limit=remaining,
                priority_case=priority_case,
                where_extra=where_extra + f" AND NOT ({repr_pred})",
                extra_params=extra_params,
            )
        )

    return claimed


def _claim(
    *,
    db_execute,
    worker_id: int,
    limit: int,
    priority_case: str,
    where_extra: str,
    extra_params: Sequence[object],
) -> List[Tuple]:
    if limit <= 0:
        return []
    params: List[object] = [worker_id, worker_id, *list(extra_params), limit]
    # Сначала учитываем AI-приоритет из crm_docs_priority_hints (если есть),
    # затем штатный приоритет очереди и свежесть задач.
    ai_order_sql = """
                CASE
                    WHEN to_regclass('public.crm_docs_priority_hints') IS NULL THEN 0
                    ELSE COALESCE((
                        SELECT h.ai_priority_score
                        FROM crm_docs_priority_hints h
                        WHERE h.contract_number = q.contract_reg_number
                          AND h.registry_type = q.table_source
                        ORDER BY h.updated_at DESC
                        LIMIT 1
                    ), 0)
                END DESC
    """.strip()
    sql = f"""
        UPDATE document_processing_queue
        SET status = 'processing',
            worker_id = %s,
            started_at = NOW()
        WHERE id IN (
            SELECT q.id
            FROM document_processing_queue q
            WHERE q.status = 'pending'
              AND (q.worker_id IS NULL OR q.worker_id = %s)
              {where_extra}
            ORDER BY
                {ai_order_sql},
                {priority_case},
                q.id DESC
            LIMIT %s
        )
        RETURNING id, contract_reg_number, table_source
    """
    return list(db_execute(sql, tuple(params), fetch=True) or [])
