"""Unit tests for Phase 3.1 Torgi Priority Sorting and Filters."""
from datetime import date, timedelta
import pytest

from src.services.torgi_workset_service import (
    MEDAL_RANKS,
    TorgiFilterParams,
)
from src.ui.components.analytics_v2.card_trust import fmt_deadline_countdown


def test_torgi_filter_params_defaults():
    params = TorgiFilterParams()
    assert params.hide_expired is True
    assert params.preliminary_medal is None
    assert params.expert_status is None
    assert params.object_family is None
    assert params.law is None


def test_torgi_filter_params_custom():
    params = TorgiFilterParams(
        preliminary_medal="GOLD",
        expert_status="Подтверждено",
        object_family="SOCIAL",
        law="44",
        search_query="школа",
        hide_expired=False,
    )
    assert params.hide_expired is False
    assert params.preliminary_medal == "GOLD"
    assert params.expert_status == "Подтверждено"
    assert params.object_family == "SOCIAL"
    assert params.law == "44"
    assert params.search_query == "школа"


def test_medal_ranks_hierarchy():
    assert MEDAL_RANKS["GOLD"] < MEDAL_RANKS["SILVER"]
    assert MEDAL_RANKS["SILVER"] < MEDAL_RANKS["BRONZE"]
    assert MEDAL_RANKS["BRONZE"] < MEDAL_RANKS["WOOD"]
    assert MEDAL_RANKS["WOOD"] < MEDAL_RANKS["UNASSESSED"]


def test_fmt_deadline_countdown():
    today = date.today()
    assert fmt_deadline_countdown(None) == "—"
    assert fmt_deadline_countdown(today - timedelta(days=1)) == "Подача завершена"
    assert fmt_deadline_countdown(today - timedelta(days=48)) == "Подача завершена"
    assert fmt_deadline_countdown(today) == "Сегодня (последний день)"
    assert fmt_deadline_countdown(today + timedelta(days=1)) == "Остался 1 день"
    assert fmt_deadline_countdown(today + timedelta(days=3)) == "Осталось 3 дня"
    assert fmt_deadline_countdown(today + timedelta(days=10)) == "Осталось 10 дней"
