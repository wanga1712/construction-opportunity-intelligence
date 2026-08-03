"""Сервис новой страницы аналитического контура."""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Iterable, Optional

import pandas as pd
import streamlit as st

from src.constants.object_quality import OBJECT_QUALITY_TIERS, TIER_LABELS
from src.constants.object_segments import OBJECT_SOURCE_OPTIONS
from src.repositories.analytics_contour_repository import AnalyticsContourRepository
from src.services.docs_match_preview import confirmed_product_groups
from src.services.object_pipeline_stage import PIPELINE_STAGE_OPTIONS
from src.services.objects_service import filter_objects

_PERIODS = {"7 дней": 7, "30 дней": 30, "90 дней": 90}
_EARLY_STAGES = {"news_signal", "project_design_ai", "positive_expertise"}
_LIMITS = {"gold": 3, "silver": 6, "bronze": 8, "early": 12}


@st.cache_resource(show_spinner=False)
def get_analytics_contour_repository(_service):
    """Кешируем слой данных в рантайме Streamlit."""
    return AnalyticsContourRepository(_service)


def _parse_date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _latest_date(item) -> Optional[date]:
    values = [
        _parse_date(item.delivery_end_date),
        _parse_date(item.delivery_start_date),
        _parse_date(item.end_date),
        _parse_date(item.start_date),
    ]
    values = [value for value in values if value is not None]
    return max(values) if values else None


def _matches_period(item, period_label: str) -> bool:
    days = _PERIODS.get(period_label)
    if not days:
        return True
    latest = _latest_date(item)
    if latest is None:
        return True
    return latest >= date.today() - timedelta(days=days)


@st.cache_data(ttl=300, show_spinner=False)
def cached_reference_data(group_pairs: tuple[tuple[str, str], ...]):
    """Справочники для фильтров и визуализации."""
    group_map = dict(group_pairs)
    source_options = tuple(
        (code, label) for code, label in OBJECT_SOURCE_OPTIONS if code != "nashdom"
    )
    stage_map = dict(PIPELINE_STAGE_OPTIONS)
    tier_map = dict(OBJECT_QUALITY_TIERS)
    return group_map, source_options, stage_map, tier_map


class AnalyticsContourService:
    """Бизнес-логика нового аналитического контура."""

    def __init__(self, repository: AnalyticsContourRepository) -> None:
        self.repository = repository

    def load(self, search_query: str = "") -> bool:
        return self.repository.load(search_query=search_query)

    def groups(self):
        return self.repository.groups(include_computers=False)

    def regions(self):
        return self.repository.regions()

    def items(self):
        return self.repository.items()

    def get_item(self, object_key: str):
        return self.repository.get_item(object_key)

    def index_meta(self):
        return self.repository.index_meta()

    def apply_filters(
        self,
        *,
        search: str,
        region_ids: set[int],
        period_label: str,
        selected_sources: set[str],
        selected_stages: set[str],
        selected_tiers: set[str],
        selected_groups: set[str],
        selected_quick_tier: str,
        only_docs: bool,
        only_volume: bool,
        only_contractor: bool,
    ):
        rows = filter_objects(
            self.items(),
            sources=selected_sources,
            search=search,
            region_id=None,
        )
        if region_ids:
            rows = [item for item in rows if item.region_id in region_ids]
        rows = [
            item
            for item in rows
            if (item.pipeline_stage_code or "news_signal") in selected_stages
        ]
        rows = [
            item for item in rows if (item.quality_tier or "wood") in selected_tiers
        ]
        rows = [
            item
            for item in rows
            if confirmed_product_groups(item).intersection(selected_groups)
        ]
        rows = [item for item in rows if _matches_period(item, period_label)]
        if selected_quick_tier != "Все":
            rows = [
                item
                for item in rows
                if (item.quality_tier or "wood").lower()
                == selected_quick_tier.lower()
            ]
        if only_docs:
            rows = [item for item in rows if (item.doc_matches or 0) > 0]
        if only_volume:
            rows = [
                item
                for item in rows
                if (item.docs_volume_preview or "").strip()
                and "не извлеч" not in (item.docs_volume_preview or "").lower()
            ]
        if only_contractor:
            rows = [item for item in rows if (item.contractor_name or "").strip()]
        rows.sort(key=lambda item: (-(item.ai_priority_score or 0), item.name or ""))
        return rows

    def kpi(self, items: Iterable):
        stage_counts = Counter(
            (item.pipeline_stage_code or "news_signal") for item in items
        )
        tier_counts = Counter((item.quality_tier or "wood") for item in items)
        updates_count = sum(
            1
            for item in items
            if (item.doc_matches or 0) > 0 and (item.ai_priority_score or 0) >= 55
        )
        early_count = sum(
            1
            for item in items
            if (item.pipeline_stage_code or "news_signal") in _EARLY_STAGES
        )
        portfolio_count = sum(
            1 for item in items if item.key in set(st.session_state.get("opened_cards", []))
        )
        return {
            "Новые карточки": stage_counts.get("news_signal", 0),
            "Gold": tier_counts.get("gold", 0),
            "Silver": tier_counts.get("silver", 0),
            "Bronze": tier_counts.get("bronze", 0),
            "Early": early_count,
            "Обновления": updates_count,
            "Портфель": portfolio_count,
        }

    def limits(self, items: Iterable):
        tier_counts = Counter((item.quality_tier or "wood") for item in items)
        early_count = sum(
            1
            for item in items
            if (item.pipeline_stage_code or "news_signal") in _EARLY_STAGES
        )
        used = {
            "gold": tier_counts.get("gold", 0),
            "silver": tier_counts.get("silver", 0),
            "bronze": tier_counts.get("bronze", 0),
            "early": early_count,
        }
        return {
            key: {"used": used[key], "limit": _LIMITS[key]} for key in _LIMITS
        }

    def stage_chart(self, items: Iterable):
        counts = Counter((item.pipeline_stage_code or "news_signal") for item in items)
        return pd.DataFrame(
            [
                {
                    "stage": label.split(")", 1)[-1].strip(),
                    "count": counts.get(code, 0),
                }
                for code, label in PIPELINE_STAGE_OPTIONS
            ]
        )

    def tier_chart(self, items: Iterable):
        counts = Counter((item.quality_tier or "wood") for item in items)
        return pd.DataFrame(
            [
                {"tier": TIER_LABELS.get(code, label), "count": counts.get(code, 0)}
                for code, label in OBJECT_QUALITY_TIERS
            ]
        )

    def category_chart(self, items: Iterable, groups: list[tuple[str, str]]):
        rows = []
        for code, label in groups:
            count = sum(
                1 for item in items if code in confirmed_product_groups(item)
            )
            rows.append({"category": label, "count": count})
        return pd.DataFrame(
            [row for row in rows if row["count"] > 0]
            or [{"category": "Нет совпадений", "count": 0}]
        )

    def companies_table(self, items: Iterable):
        companies = Counter(
            (item.customer_name or item.balance_holder or "Не найдено")
            for item in items
        )
        return pd.DataFrame(
            companies.most_common(20), columns=["Компания", "Объекты"]
        )

    def table_view(self, items: Iterable, groups_map: dict[str, str]):
        rows = []
        for item in items:
            groups = ", ".join(
                groups_map.get(code, code)
                for code in sorted(confirmed_product_groups(item))[:3]
            )
            rows.append(
                {
                    "Ключ": item.key,
                    "Название": item.name,
                    "Стадия": item.pipeline_stage_label,
                    "Уровень": item.quality_tier,
                    "Категория": groups or "—",
                    "Регион": item.region or "—",
                    "AI score": int(item.ai_priority_score or 0),
                }
            )
        return pd.DataFrame(rows)
