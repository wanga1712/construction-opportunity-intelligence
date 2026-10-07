"""Minimal tests for the universal procurement opportunity classifier."""
from __future__ import annotations

from src.services.procurement_opportunity_ai import (
    auto_category_code,
    auto_subcategory_code,
    normalize_result,
)
from src.services import procurement_opportunity_store as store


COMPUTERS_TAXONOMY = [
    {
        "category_code": "computers",
        "category_name": "Компьютерная техника",
        "subcategories": [
            {"subcategory_code": "laptops", "subcategory_name": "Ноутбуки"},
            {"subcategory_code": "desktop_computers", "subcategory_name": "Настольные компьютеры"},
        ],
    }
]

LIGHTING_TAXONOMY = [
    {
        "category_code": "lighting",
        "category_name": "Светотехника",
        "subcategories": [
            {"subcategory_code": "road_street", "subcategory_name": "Автодорожное и уличное"},
        ],
    }
]


def test_direct_computers():
    raw = {
        "procurement_mode": "direct_supply",
        "object_present": True,
        "object": {
            "primary_class": "Социальный объект",
            "subcategory": None,
            "object_type": "Школа",
            "object_subtype": None,
            "work_type": None,
        },
        "opportunities": [
            {
                "category_code": "computers",
                "category_name": "Компьютерная техника",
                "subcategory_code": "laptops",
                "subcategory_name": "Ноутбуки",
                "product_name": "Ноутбуки",
                "quantity": 40,
                "unit": "шт",
                "taxonomy_action": "existing",
                "confidence": 0.94,
            }
        ],
        "classification_confidence": 0.94,
    }

    result = normalize_result(raw, COMPUTERS_TAXONOMY)

    assert result["procurement_mode"] == "direct_supply"
    assert result["object_present"] is False
    assert result["opportunities"][0]["category_code"] == "computers"
    assert result["opportunities"][0]["subcategory_code"] == "laptops"


def test_lighting_inside_road_works():
    raw = {
        "procurement_mode": "works_with_products",
        "object_present": True,
        "object": {
            "primary_class": "Инфраструктура",
            "subcategory": "Дорожная инфраструктура",
            "object_type": "Автомобильная дорога",
            "object_subtype": None,
            "work_type": "Капитальный ремонт",
        },
        "opportunities": [
            {
                "category_code": "lighting",
                "category_name": "Светотехника",
                "subcategory_code": "road_street",
                "subcategory_name": "Автодорожное и уличное",
                "product_name": "Уличные светильники",
                "quantity": None,
                "unit": "шт",
                "taxonomy_action": "existing",
                "confidence": 0.91,
            }
        ],
        "classification_confidence": 0.91,
    }

    result = normalize_result(raw, LIGHTING_TAXONOMY)

    assert result["procurement_mode"] == "works_with_products"
    assert result["object_present"] is True
    assert "дорога" in str(result["object"]["object_type"]).lower()
    assert any(
        opportunity["category_code"] == "lighting"
        for opportunity in result["opportunities"]
    )


class _FakeDb:
    def __init__(self):
        self.updates = []
        self.queries = []

    def execute_query(self, sql, params=None):
        self.queries.append((sql, params))
        if "status = 'candidate'" in sql:
            return [
                {
                    "id": 1,
                    "parent_name": "Медицина",
                    "parent_name_norm": "медицина",
                    "subcategory_name": "Медицинские расходные материалы",
                    "subcategory_name_norm": "медицинские расходные материалы",
                    "sample_product_name": "Латексные перчатки",
                    "procurement_count": 3,
                    "confidence_sum": 2.55,
                }
            ]
        if "FROM crm_product_categories" in sql:
            return [{"id": 101}]
        if "FROM crm_product_subcategories" in sql:
            return [{"id": 201}]
        return []

    def execute_update(self, sql, params=None):
        self.updates.append((sql, params))


def test_dynamic_medical_taxonomy():
    db = _FakeDb()

    for confidence in (0.85, 0.90, 0.80):
        store.record_discovery(
            db,
            parent_name="Медицина",
            subcategory_name="Медицинские расходные материалы",
            sample_product_name="Латексные перчатки",
            confidence=confidence,
            total_amount=1000.0,
            is_new_procurement=True,
        )

    discovery_upserts = [
        call
        for call in db.updates
        if "INSERT INTO crm_product_taxonomy_discovery" in call[0]
    ]
    assert len(discovery_upserts) == 3
    assert all(call[1][5] == 1 for call in discovery_upserts)

    promoted = store.promote_discovery(db)

    assert len(promoted) == 1
    category_code = auto_category_code("Медицина")
    subcategory_code = auto_subcategory_code(
        "Медицина", "Медицинские расходные материалы"
    )
    assert promoted[0]["category_code"] == category_code
    assert promoted[0]["subcategory_code"] == subcategory_code

    category_inserts = [
        call for call in db.updates if "INSERT INTO crm_product_categories" in call[0]
    ]
    subcategory_inserts = [
        call for call in db.updates if "INSERT INTO crm_product_subcategories" in call[0]
    ]
    assert any(category_code in call[1] for call in category_inserts)
    assert any(subcategory_code in call[1] for call in subcategory_inserts)
    assert any(
        "SET status = 'promoted'" in call[0]
        for call in db.updates
    )
