"""
Daily priority recalculator.

Sweeps all pending rows and updates their priority_class / priority_score
based on fresh deadline data from the source registries.

Run every day at 06:00, before daemon workers start.
Also runs on-demand when submission_end_at changes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from .queue_priority_calculator import (
    PriorityInput,
    QueuePriorityCalculator,
)

_HOLIDAYS_RU = frozenset()  # TODO: populate from DB or config


def _business_days_until(target, now: Optional[datetime] = None) -> Optional[int]:
    from datetime import date as date_type
    if target is None:
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    if isinstance(target, date_type) and not isinstance(target, datetime):
        target = datetime(target.year, target.month, target.day, tzinfo=timezone.utc)
    if isinstance(target, datetime):
        target = target.replace(tzinfo=timezone.utc) if target.tzinfo is None else target
    else:
        return None
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
    if target <= now:
        return -1
    delta_days = (target.date() - now.date()).days
    workdays = 0
    cur = now.date()
    for _ in range(delta_days):
        cur_next = cur.__class__.fromordinal(cur.toordinal() + 1)
        if cur_next.weekday() < 5 and cur_next not in _HOLIDAYS_RU:
            workdays += 1
        cur = cur_next
    return workdays


_REGISTRY_SUBMISSION_SQL = {
    "reestr_contract_44_fz":          "end_date",
    "reestr_contract_223_fz":         "end_date",
    "reestr_contract_44_fz_awarded":  "end_date",
    "reestr_contract_223_fz_awarded": "end_date",
}

_REGISTRY_PRICE_SQL = {
    "reestr_contract_44_fz":          "initial_price",
    "reestr_contract_223_fz":         "initial_price",
    "reestr_contract_44_fz_awarded":  "initial_price",
    "reestr_contract_223_fz_awarded": "initial_price",
}

# Sources to include in GOLD median stats (active registries only)
_MEDIAN_SOURCES = [
    "reestr_contract_44_fz",
    "reestr_contract_223_fz",
]

# Feedback boost: raise priority_score by this amount when user marks a tender
_FEEDBACK_BOOST = 20
_FEEDBACK_LANE  = "crm_active_hot"


class PriorityRecalculator:
    """Recalculates queue priorities in bulk."""

    def __init__(self, db, logger, required_workdays: int = 2, batch_size: int = 500):
        self.db = db
        self.logger = logger
        self.required_workdays = required_workdays
        self.batch_size = batch_size
        self.calc = QueuePriorityCalculator()
        # category stats cache: table_source → (median, p75)
        self._category_stats: Dict[str, Tuple[Optional[int], Optional[int]]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_full_sweep(self, force: bool = False) -> int:
        """
        Recalculate all pending rows whose next_priority_recalc_at <= NOW()
        (or all pending rows when force=True).
        Returns number of rows updated.
        """
        self.logger.info("[recalc] Запуск пересчёта приоритетов очереди...")

        # Load market benchmarks once per sweep
        self._category_stats = self._load_category_stats()
        self.logger.info(
            f"[recalc] Загружена медиана по {len(self._category_stats)} источникам: "
            + ", ".join(
                f"{src}={int(med or 0)//1000}k"
                for src, (med, _) in self._category_stats.items()
            )
        )

        # Apply user feedback boosts before scoring
        boosted = self._apply_feedback_boosts()
        if boosted:
            self.logger.info(f"[recalc] Применено пользовательских буст-отметок: {boosted}")

        where_clause = "" if force else "AND (next_priority_recalc_at IS NULL OR next_priority_recalc_at <= NOW())"
        offset = 0
        total_updated = 0

        while True:
            rows = self.db.execute_query(
                "tender_monitor",
                f"""
                SELECT
                    q.id,
                    q.contract_reg_number,
                    q.table_source,
                    q.submission_end_at,
                    q.initial_price,
                    q.category_code,
                    q.required_workdays,
                    q.aging_hours,
                    COALESCE(q.aging_hours, 0)
                      + EXTRACT(EPOCH FROM (NOW() - q.created_at)) / 3600 AS total_aging_hours
                FROM document_processing_queue q
                WHERE q.status = 'pending'
                  {where_clause}
                ORDER BY q.id
                LIMIT %s OFFSET %s
                """,
                (self.batch_size, offset),
                fetch=True,
            ) or []

            if not rows:
                break

            for row in rows:
                (
                    task_id, contract_number, table_source,
                    submission_end_at, initial_price, category_code,
                    required_workdays, _aging_col, total_aging_hours,
                ) = row

                if submission_end_at is None:
                    submission_end_at = self._fetch_submission_end(contract_number, table_source)
                if initial_price is None:
                    initial_price = self._fetch_price(contract_number, table_source)

                remaining = _business_days_until(submission_end_at)
                req = required_workdays or self.required_workdays

                # Resolve category market benchmarks
                median_price, p75_price = self._get_category_benchmarks(table_source, initial_price)

                inp = PriorityInput(
                    contract_number=contract_number,
                    table_source=table_source,
                    initial_price=initial_price,
                    submission_end_at=submission_end_at,
                    remaining_workdays=remaining,
                    required_workdays=req,
                    category_code=category_code,
                    aging_hours=int(total_aging_hours or 0),
                    hist_median_price=median_price,
                    hist_p75_price=p75_price,
                )
                result = self.calc.calculate(inp)

                self.db.execute_query(
                    "tender_monitor",
                    """
                    UPDATE document_processing_queue
                    SET
                        queue_type                  = %s,
                        priority_class              = %s,
                        priority_score              = %s,
                        deadline_slack              = %s,
                        predicted_gold_prob         = %s,
                        commercial_scale_score      = %s,
                        deadline_feasibility_score  = %s,
                        remaining_workdays          = %s,
                        submission_end_at           = COALESCE(submission_end_at, %s),
                        initial_price               = COALESCE(initial_price, %s),
                        priority_reason_json        = %s,
                        priority_model_version      = %s,
                        priority_calculated_at      = NOW(),
                        next_priority_recalc_at     = NOW() + INTERVAL '1 day'
                    WHERE id = %s
                    """,
                    (
                        result.queue_type,
                        result.priority_class,
                        result.priority_score,
                        result.deadline_slack,
                        float(result.predicted_gold_prob),
                        result.commercial_scale_score,
                        result.deadline_feasibility_score,
                        remaining,
                        submission_end_at,
                        initial_price,
                        json.dumps({"codes": result.reason_codes}),
                        result.model_version,
                        task_id,
                    ),
                )
                total_updated += 1

            offset += self.batch_size
            if total_updated % 1000 == 0 and total_updated > 0:
                self.logger.info(f"[recalc] Обработано {total_updated} задач...")

        self.logger.info(f"[recalc] Готово. Обновлено {total_updated} задач.")
        return total_updated

    # ------------------------------------------------------------------
    # GOLD median: load market benchmarks from active registry
    # ------------------------------------------------------------------

    def _load_category_stats(self) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
        """
        Computes PERCENTILE_CONT(0.5) and PERCENTILE_CONT(0.75) of initial_price
        per source table (proxy for category) over last 180 days.
        Returns dict: table_source → (median_price, p75_price).
        """
        unions = "\n    UNION ALL\n    ".join(
            f"SELECT '{src}' AS src, initial_price "
            f"FROM {src} "
            f"WHERE initial_price > 0 AND end_date > NOW() - INTERVAL '180 days'"
            for src in _MEDIAN_SOURCES
        )
        sql = f"""
        SELECT
            src,
            PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY initial_price::numeric)::bigint AS median_price,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY initial_price::numeric)::bigint AS p75_price
        FROM (
            {unions}
        ) data
        GROUP BY src
        """
        try:
            rows = self.db.execute_query("tender_monitor", sql, fetch=True) or []
            return {row[0]: (row[1], row[2]) for row in rows}
        except Exception as e:
            self.logger.warning(f"[recalc] Не удалось загрузить медианы: {e}")
            return {}

    def _get_category_benchmarks(
        self, table_source: str, initial_price: Optional[int]
    ) -> Tuple[Optional[int], Optional[int]]:
        """
        Returns (median, p75) for the given table_source.
        Falls back to awarded → open source if awarded not in stats.
        """
        if table_source in self._category_stats:
            return self._category_stats[table_source]
        # awarded → use open counterpart
        base = table_source.replace("_awarded", "")
        if base in self._category_stats:
            return self._category_stats[base]
        return None, None

    # ------------------------------------------------------------------
    # User feedback boosts
    # ------------------------------------------------------------------

    def _apply_feedback_boosts(self) -> int:
        """
        Reads unprocessed rows from crm_priority_feedback and boosts
        the matching queue entries to crm_active_hot lane + higher score.
        Marks feedback rows as applied.
        """
        try:
            rows = self.db.execute_query(
                "tender_monitor",
                """
                SELECT id, contract_reg_number, table_source
                FROM crm_priority_feedback
                WHERE applied_at IS NULL
                ORDER BY created_at
                LIMIT 200
                """,
                fetch=True,
            ) or []
        except Exception:
            return 0  # table may not exist yet

        if not rows:
            return 0

        boosted = 0
        for fb_id, contract_number, table_source in rows:
            try:
                self.db.execute_query(
                    "tender_monitor",
                    """
                    UPDATE document_processing_queue
                    SET
                        queue_lane     = %s,
                        priority_score = LEAST(100, priority_score + %s),
                        priority_reason_json = priority_reason_json || '{"feedback_boost": true}'::jsonb,
                        next_priority_recalc_at = NOW() + INTERVAL '1 hour'
                    WHERE contract_reg_number = %s
                      AND status = 'pending'
                    """,
                    (_FEEDBACK_LANE, _FEEDBACK_BOOST, contract_number),
                )
                self.db.execute_query(
                    "tender_monitor",
                    "UPDATE crm_priority_feedback SET applied_at = NOW() WHERE id = %s",
                    (fb_id,),
                )
                boosted += 1
            except Exception as e:
                self.logger.warning(f"[recalc] Ошибка буста feedback id={fb_id}: {e}")

        return boosted

    # ------------------------------------------------------------------
    # Registry lookups
    # ------------------------------------------------------------------

    def _fetch_submission_end(self, contract_number: str, table_source: str):
        col = _REGISTRY_SUBMISSION_SQL.get(table_source, "end_date")
        try:
            rows = self.db.execute_query(
                "tender_monitor",
                f"SELECT {col} FROM {table_source} WHERE contract_number = %s LIMIT 1",
                (contract_number,),
                fetch=True,
            )
            return rows[0][0] if rows else None
        except Exception:
            return None

    def _fetch_price(self, contract_number: str, table_source: str):
        col = _REGISTRY_PRICE_SQL.get(table_source, "initial_price")
        try:
            rows = self.db.execute_query(
                "tender_monitor",
                f"SELECT {col} FROM {table_source} WHERE contract_number = %s LIMIT 1",
                (contract_number,),
                fetch=True,
            )
            return rows[0][0] if rows else None
        except Exception:
            return None
