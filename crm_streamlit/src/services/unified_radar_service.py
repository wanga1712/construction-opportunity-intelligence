"""Unified Radar сервис: объединение сигналов из нескольких контуров.

Связан с:
- opportunity_radar (положительные заключения),
- NashDom (объекты),
- план закупок (если таблица доступна в tender_monitor).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List

from modules.crm.analytics.tender_row_utils import query_dicts
from src.services.opportunity_radar import RadarFilters, fetch_expertise_radar
from src.services.unified_radar_models import UnifiedRadarCard


@dataclass
class UnifiedRadarResult:
    """Результат загрузки по вкладкам Unified Radar."""

    positive_rows: List[dict]
    nashdom_rows: List[dict]
    procurement_plan_rows: List[dict]
    unified_cards: List[UnifiedRadarCard]


class UnifiedRadarService:
    """Агрегирует сигналы по объектам и строит unified-карточки."""

    def __init__(self, *, tender_db=None, radar_db=None) -> None:
        self.tender_db = tender_db
        self.radar_db = radar_db

    def load(self, filters: RadarFilters) -> UnifiedRadarResult:
        positive = self._load_positive(filters)
        nashdom = self._load_nashdom(filters)
        plan_rows = self._load_procurement_plan(filters)
        cards = self._merge_to_cards(positive, nashdom, plan_rows)
        cards.sort(key=lambda x: (-int(x.ai_priority_score or 0), x.object_name))
        return UnifiedRadarResult(
            positive_rows=positive,
            nashdom_rows=nashdom,
            procurement_plan_rows=plan_rows,
            unified_cards=cards,
        )

    def _load_positive(self, filters: RadarFilters) -> List[dict]:
        try:
            return fetch_expertise_radar(self.tender_db, filters)
        except Exception:
            return []

    def _load_nashdom(self, filters: RadarFilters) -> List[dict]:
        if not self.radar_db:
            return []
        q = (filters.region_query or "").strip().lower()
        rows: List[dict] = []
        try:
            raw = self.radar_db.execute_query(
                """
                SELECT object_id, object_name, full_address, region_name
                FROM object
                ORDER BY object_id DESC
                LIMIT %s
                """,
                (int(filters.limit),),
                fetch=True,
            ) or []
            for row in raw:
                r = dict(row) if isinstance(row, dict) else {}
                text = " ".join(
                    str(r.get(x) or "") for x in ("object_name", "full_address", "region_name")
                ).lower()
                if q and q not in text:
                    continue
                rows.append(r)
        except Exception:
            return []
        return rows

    def _load_procurement_plan(self, filters: RadarFilters) -> List[dict]:
        if not self.tender_db:
            return []
        # В разных инсталляциях имя таблицы может отличаться — проверяем кандидаты.
        candidates = (
            "procurement_plan_44_fz",
            "plan_procurement_44_fz",
            "zakupki_plan_44_fz",
        )
        table_name = ""
        for cand in candidates:
            try:
                reg = query_dicts(
                    self.tender_db,
                    "SELECT to_regclass(%s) AS reg",
                    (f"public.{cand}",),
                )
                if reg and reg[0].get("reg"):
                    table_name = cand
                    break
            except Exception:
                continue
        if not table_name:
            return []
        params: list = [int(filters.limit)]
        where = "TRUE"
        if (filters.region_query or "").strip():
            where = "(region_name ILIKE %s OR object_name ILIKE %s)"
            q = f"%{filters.region_query.strip()}%"
            params = [q, q, int(filters.limit)]
        try:
            return query_dicts(
                self.tender_db,
                f"""
                SELECT id, object_name, region_name, customer_name, planned_publish_date
                FROM {table_name}
                WHERE {where}
                ORDER BY planned_publish_date DESC NULLS LAST, id DESC
                LIMIT %s
                """,
                tuple(params),
            )
        except Exception:
            return []

    def _merge_to_cards(self, positive: List[dict], nashdom: List[dict], plan_rows: List[dict]) -> List[UnifiedRadarCard]:
        by_uid: Dict[str, UnifiedRadarCard] = {}
        for row in positive:
            uid = self._uid(
                row.get("expertise_number"),
                row.get("object_name"),
                row.get("region_name"),
            )
            card = by_uid.get(uid) or UnifiedRadarCard(object_uid=uid, object_name=row.get("object_name") or "—")
            card.region_name = row.get("region_name") or card.region_name
            card.expertise_number = row.get("expertise_number") or card.expertise_number
            card.planner_name = row.get("planner_organization_info") or card.planner_name
            card.customer_name = row.get("technical_customer_organization_info") or card.customer_name
            card.tender_match_count = int(row.get("tender_match_count") or card.tender_match_count or 0)
            card.ai_priority_score = max(int(row.get("radar_priority") or 0), card.ai_priority_score)
            card.ai_priority_reason = row.get("source_label") or card.ai_priority_reason
            card.signal_flags.positive_expertise = True
            card.signal_flags.projector_found = bool(card.planner_name)
            card.signal_flags.customer_found = bool(card.customer_name)
            card.signal_flags.tender_found = card.tender_match_count > 0
            card.sources = sorted(set(card.sources + ["positive_expertise"]))
            by_uid[uid] = card
        for row in nashdom:
            uid = self._uid(None, row.get("object_name"), row.get("region_name"))
            card = by_uid.get(uid) or UnifiedRadarCard(object_uid=uid, object_name=row.get("object_name") or "—")
            card.region_name = row.get("region_name") or card.region_name
            card.address = row.get("full_address") or card.address
            card.domrf_object_id = str(row.get("object_id") or card.domrf_object_id or "")
            card.signal_flags.nashdom = True
            card.ai_priority_score = max(card.ai_priority_score, 35)
            card.sources = sorted(set(card.sources + ["nashdom"]))
            by_uid[uid] = card
        for row in plan_rows:
            uid = self._uid(None, row.get("object_name"), row.get("region_name"))
            card = by_uid.get(uid) or UnifiedRadarCard(object_uid=uid, object_name=row.get("object_name") or "—")
            card.region_name = row.get("region_name") or card.region_name
            card.customer_name = row.get("customer_name") or card.customer_name
            card.signal_flags.procurement_plan = True
            card.signal_flags.customer_found = bool(card.customer_name)
            card.ai_priority_score = max(card.ai_priority_score, 60)
            card.ai_priority_reason = card.ai_priority_reason or "План закупок"
            card.sources = sorted(set(card.sources + ["procurement_plan"]))
            by_uid[uid] = card
        for card in by_uid.values():
            card.recompute_status()
        return list(by_uid.values())

    @staticmethod
    def _uid(expertise_number, object_name, region_name) -> str:
        if expertise_number:
            return f"exp:{str(expertise_number).strip().lower()}"
        name = str(object_name or "").strip().lower()
        region = str(region_name or "").strip().lower()
        return f"obj:{region}:{name}"[:300]

