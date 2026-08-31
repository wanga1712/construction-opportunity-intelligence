"""
CRM → document_processing_queue bridge.

Matches crm_tender_match_cache rows to actual registry contract_numbers,
then inserts/updates queue entries with proper lane and priority fields.

Usage (standalone):
    python -m document_processor.crm_queue_bridge

Usage (from daemon / scheduler):
    from document_processor.crm_queue_bridge import CrmQueueBridge
    bridge = CrmQueueBridge(db, logger)
    report = bridge.run()
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Optional

from .queue_priority_calculator import PriorityInput, QueuePriorityCalculator

REQUIRED_WORKDAYS_DEFAULT = 2

# Lane assignment rules (evaluated top-to-bottom, first match wins)
LANE_CRM_HOT    = "crm_active_hot"
LANE_OPEN       = "open_active"
LANE_AWARDED    = "awarded_recent"
LANE_HIST       = "historical_awarded"
LANE_RETRY      = "retry"

LANE_RANK = {
    LANE_CRM_HOT: 1,
    LANE_OPEN:    2,
    LANE_AWARDED: 3,
    LANE_RETRY:   4,
    LANE_HIST:    5,
}


def _to_datetime(val) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=timezone.utc) if val.tzinfo is None else val
    if isinstance(val, date):
        return datetime(val.year, val.month, val.day, tzinfo=timezone.utc)
    return None


def _business_days_until(target) -> Optional[int]:
    dt = _to_datetime(target)
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    if dt <= now:
        return -1
    delta = (dt.date() - now.date()).days
    workdays = sum(
        1 for i in range(1, delta + 1)
        if (now.date().__class__.fromordinal(now.date().toordinal() + i)).weekday() < 5
    )
    return workdays


class CrmQueueBridge:
    def __init__(self, db, logger, required_workdays: int = REQUIRED_WORKDAYS_DEFAULT):
        self.db = db
        self.logger = logger
        self.required_workdays = required_workdays
        self.calc = QueuePriorityCalculator()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> dict:
        """
        Full bridge run:
          1. Fetch CRM match cache rows + join registry for contract_number
          2. Print report
          3. Insert/update queue entries
        Returns report dict.
        """
        self.logger.info("[crm_bridge] Запуск моста CRM → очередь...")

        candidates = self._fetch_candidates()
        report = self._build_report(candidates)
        self._log_report(report)

        inserted = updated = skipped = 0
        for c in candidates:
            if c["contract_number"] is None:
                continue  # не сопоставлено
            action = self._upsert(c)
            if action == "inserted":
                inserted += 1
            elif action == "updated":
                updated += 1
            else:
                skipped += 1

        report["inserted"] = inserted
        report["updated"]  = updated
        report["skipped"]  = skipped
        self.logger.info(
            f"[crm_bridge] Готово: вставлено={inserted} обновлено={updated} пропущено={skipped}"
        )
        return report

    # ------------------------------------------------------------------
    # Step 1: fetch + join
    # ------------------------------------------------------------------

    def _fetch_candidates(self) -> list[dict]:
        """
        Returns one dict per crm_tender_match_cache row, enriched with
        contract_number, submission_end_at, initial_price from the registry.
        """
        rows = self.db.execute_query(
            "tender_monitor",
            """
            SELECT
                c.id            AS cache_id,
                c.source_table  AS table_source,
                c.source_id,
                c.crm_profile_id,
                c.match_score,
                -- registry data
                r44.contract_number  AS cn_44,
                r44.end_date         AS end_44,
                r44.initial_price    AS price_44,
                r223.contract_number AS cn_223,
                r223.end_date        AS end_223,
                r223.initial_price   AS price_223
            FROM crm_tender_match_cache c
            LEFT JOIN reestr_contract_44_fz  r44
                   ON r44.id = c.source_id AND c.source_table = 'reestr_contract_44_fz'
            LEFT JOIN reestr_contract_223_fz r223
                   ON r223.id = c.source_id AND c.source_table = 'reestr_contract_223_fz'
            """,
            fetch=True,
        ) or []

        candidates = []
        for row in rows:
            (
                cache_id, table_source, source_id, crm_profile_id, match_score,
                cn_44, end_44, price_44,
                cn_223, end_223, price_223,
            ) = row

            if table_source == "reestr_contract_44_fz":
                contract_number   = cn_44
                submission_end_at = _to_datetime(end_44)
                initial_price     = price_44
            elif table_source == "reestr_contract_223_fz":
                contract_number   = cn_223
                submission_end_at = _to_datetime(end_223)
                initial_price     = price_223
            else:
                contract_number   = None
                submission_end_at = None
                initial_price     = None

            candidates.append({
                "cache_id":         cache_id,
                "table_source":     table_source,
                "source_id":        source_id,
                "crm_profile_id":   crm_profile_id,
                "match_score":      match_score or 0,
                "contract_number":  contract_number,
                "submission_end_at": submission_end_at,
                "initial_price":    int(initial_price) if initial_price else None,
            })
        return candidates

    # ------------------------------------------------------------------
    # Step 2: report
    # ------------------------------------------------------------------

    def _build_report(self, candidates: list[dict]) -> dict:
        total          = len(candidates)
        matched        = sum(1 for c in candidates if c["contract_number"])
        not_matched    = total - matched
        open_sub       = 0
        closed_sub     = 0
        already_queued = 0
        absent         = 0

        for c in candidates:
            if not c["contract_number"]:
                continue
            remaining = _business_days_until(c["submission_end_at"])
            if remaining is not None and remaining >= 0:
                open_sub += 1
            else:
                closed_sub += 1

            in_q = self._in_queue(c["contract_number"], c["table_source"])
            if in_q:
                already_queued += 1
            else:
                absent += 1

        return {
            "total_crm":       total,
            "matched":         matched,
            "not_matched":     not_matched,
            "open_submission": open_sub,
            "closed_submission": closed_sub,
            "already_queued":  already_queued,
            "absent":          absent,
        }

    def _log_report(self, report: dict) -> None:
        lines = [
            "[crm_bridge] === Отчёт сопоставления CRM → очередь ===",
            f"  Карточек CRM:                    {report['total_crm']}",
            f"  Точно сопоставлено с реестром:   {report['matched']}",
            f"  Не удалось сопоставить:          {report['not_matched']}",
            f"  Подача открыта:                  {report['open_submission']}",
            f"  Подача завершена:                {report['closed_submission']}",
            f"  Уже есть в очереди:              {report['already_queued']}",
            f"  Отсутствует в очереди:           {report['absent']}",
        ]
        for line in lines:
            self.logger.info(line)
            print(line, flush=True)

    # ------------------------------------------------------------------
    # Step 3: upsert
    # ------------------------------------------------------------------

    def _in_queue(self, contract_number: str, table_source: str) -> bool:
        rows = self.db.execute_query(
            "tender_monitor",
            "SELECT 1 FROM document_processing_queue "
            "WHERE contract_reg_number=%s AND table_source=%s LIMIT 1",
            (contract_number, table_source),
            fetch=True,
        )
        return bool(rows)

    def _upsert(self, c: dict) -> str:
        contract_number   = c["contract_number"]
        table_source      = c["table_source"]
        submission_end_at = c["submission_end_at"]
        initial_price     = c["initial_price"]
        match_score       = c["match_score"]

        remaining  = _business_days_until(submission_end_at)
        req        = self.required_workdays
        slack      = (remaining - req) if remaining is not None else None
        sub_closed = remaining is not None and remaining < 0

        # Determine lane
        if sub_closed:
            lane = LANE_HIST
        elif remaining is not None and remaining >= req and match_score >= 6:
            lane = LANE_CRM_HOT
        elif remaining is not None and remaining >= 0:
            lane = LANE_OPEN
        else:
            lane = LANE_OPEN

        # Calculate priority
        inp = PriorityInput(
            contract_number=contract_number,
            table_source=table_source,
            initial_price=initial_price,
            submission_end_at=submission_end_at,
            remaining_workdays=remaining,
            required_workdays=req,
        )
        res = self.calc.calculate(inp)

        # Check if already in queue
        existing = self.db.execute_query(
            "tender_monitor",
            "SELECT id, queue_lane, priority_score FROM document_processing_queue "
            "WHERE contract_reg_number=%s AND table_source=%s LIMIT 1",
            (contract_number, table_source),
            fetch=True,
        )

        if existing:
            row_id = existing[0][0]
            # Upgrade lane if CRM info makes it hotter
            current_lane  = existing[0][1]
            current_score = existing[0][2] or 0
            new_lane_rank  = LANE_RANK.get(lane, 99)
            curr_lane_rank = LANE_RANK.get(current_lane, 99)

            if new_lane_rank < curr_lane_rank or res.priority_score > current_score:
                self.db.execute_query(
                    "tender_monitor",
                    """
                    UPDATE document_processing_queue SET
                        queue_lane           = %s,
                        queue_source         = 'crm_v2',
                        crm_card_id          = %s,
                        crm_match_score      = %s,
                        priority_class       = %s,
                        priority_score       = %s,
                        deadline_slack       = %s,
                        remaining_workdays   = %s,
                        submission_end_at    = COALESCE(submission_end_at, %s),
                        initial_price        = COALESCE(initial_price, %s),
                        priority_reason_json = %s,
                        priority_calculated_at = NOW(),
                        next_priority_recalc_at = NOW() + INTERVAL '1 day'
                    WHERE id = %s
                    """,
                    (
                        lane,
                        c["cache_id"],
                        match_score,
                        res.priority_class,
                        res.priority_score,
                        slack,
                        remaining,
                        submission_end_at,
                        initial_price,
                        json.dumps({"codes": res.reason_codes, "crm": True}),
                        row_id,
                    ),
                )
                return "updated"
            return "skipped"

        # Insert new
        self.db.execute_query(
            "tender_monitor",
            """
            INSERT INTO document_processing_queue (
                contract_reg_number, table_source, status,
                queue_lane, queue_source, queue_type,
                crm_card_id, crm_match_score,
                submission_end_at, initial_price,
                priority_class, priority_score,
                remaining_workdays, required_workdays, deadline_slack,
                priority_reason_json, priority_model_version,
                priority_calculated_at, next_priority_recalc_at
            )
            SELECT
                %s, %s, 'pending',
                %s, 'crm_v2', %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, 'v1_formula',
                NOW(), NOW() + INTERVAL '1 day'
            WHERE NOT EXISTS (
                SELECT 1 FROM document_processing_queue
                WHERE contract_reg_number = %s AND table_source = %s
            )
            """,
            (
                contract_number, table_source,
                lane, res.queue_type,
                c["cache_id"], match_score,
                submission_end_at, initial_price,
                res.priority_class, res.priority_score,
                remaining, req, slack,
                json.dumps({"codes": res.reason_codes, "crm": True}),
                # WHERE NOT EXISTS params
                contract_number, table_source,
            ),
        )
        return "inserted"
