"""Read-side tests for the category-first analytics service."""
from __future__ import annotations

import pytest

from src.services.category_overview_service import (
    get_category_overview,
    get_category_procurements,
    get_category_summary,
)


class _FakeDb:
    def __init__(self):
        self.queries = []

    def execute_query(self, sql, params=None):
        self.queries.append((sql, params))
        if "sub_proc_agg" in sql:
            return [
                {
                    "category_code": "lighting",
                    "subcategory_code": "road_street",
                    "subcategory_name": "Автодорожное и уличное",
                    "procurement_count": 2,
                    "total_amount": 800,
                    "direct_supply_count": 0,
                    "works_with_products_count": 2,
                }
            ]
        if "cat_proc_agg" in sql:
            return [
                {
                    "category_code": "lighting",
                    "procurement_count": 3,
                    "total_amount": 1200,
                    "direct_supply_count": 1,
                    "works_with_products_count": 2,
                    "initial_gold": 0,
                    "initial_silver": 2,
                    "initial_bronze": 1,
                    "initial_wood": 0,
                    "current_gold": 1,
                    "current_silver": 1,
                    "current_bronze": 1,
                    "current_wood": 0,
                }
            ]
        if "cat_proc AS" in sql and "global_amount" in sql:
            return [
                {
                    "category_count": 2,
                    "opportunity_count": 5,
                    "total_amount": 2000,
                    "gold": 1,
                    "silver": 2,
                    "bronze": 1,
                    "wood": 1,
                }
            ]
        if "DISTINCT ON" in sql:
            return [
                {
                    "procurement_id": 10,
                    "auction_name": "Поставка светильников",
                    "initial_price": 500,
                    "customer": "Заказчик",
                    "okpd_code": "27.40",
                    "okpd_name": "Освещение",
                    "category_code": "lighting",
                    "subcategory_code": "road_street",
                    "subcategory_name": "Автодорожное и уличное",
                    "opportunity_track": "DIRECT_SUPPLY",
                    "candidate_initial_medal": "SILVER",
                    "current_effective_medal": "SILVER",
                    "confirmed_base_medal": None,
                }
            ]
        if "FROM crm_product_categories" in sql:
            return [
                {"category_code": "lighting", "category_name": "Светотехника", "sort_order": 10},
                {"category_code": "computers", "category_name": "Компьютерная техника", "sort_order": 20},
            ]
        return []


def test_get_category_overview_maps_medals_and_subcategories():
    db = _FakeDb()
    result = get_category_overview(db)

    categories = result["categories"]
    assert len(categories) == 2
    lighting = next(c for c in categories if c["category_code"] == "lighting")
    assert lighting["procurement_count"] == 3
    assert lighting["initial_medals"]["silver"] == 2
    assert lighting["current_medals"]["gold"] == 1
    assert lighting["subcategories"][0]["subcategory_code"] == "road_street"


def test_get_category_summary_selects_medal_view():
    db = _FakeDb()
    result = get_category_summary(db, medal_view="initial")

    assert result["category_count"] == 2
    assert result["opportunity_count"] == 5
    assert result["total_amount"] == 2000
    assert result["medals"]["gold"] == 1

    assert "cm.initial_medal" in db.queries[-1][0]
    get_category_summary(db, medal_view="current")
    assert "cm.current_medal" in db.queries[-1][0]
    with pytest.raises(ValueError):
        get_category_summary(db, medal_view="confirmed")


def test_get_category_procurements_normalizes_direct_supply():
    db = _FakeDb()
    rows = get_category_procurements(db, "lighting", "road_street")

    assert len(rows) == 1
    assert rows[0]["procurement_mode"] == "direct_supply"
    assert rows[0]["subcategory_name"] == "Автодорожное и уличное"
    assert rows[0]["candidate_initial_medal"] == "SILVER"
