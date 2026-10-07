"""Deterministic resolver unit tests (no DB, no model)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import product_subcategory_resolver as r  # noqa: E402


def _ctx() -> r.ResolverContext:
    return r.ResolverContext(
        product_by_category={
            "computers": {
                "servers", "all_in_one_computers", "network_equipment",
                "desktop_computers", "laptops", "workstation_kits",
                "monitors", "computer_peripherals",
            },
            "lighting": {
                "lighting_poles", "street_luminaires", "floodlights",
                "downlights", "indoor_luminaires", "architectural_lighting",
                "lighting_controls", "emergency_evac", "explosion_proof",
                "linear_indoor",
            },
        },
        terms_by_category={
            "computers": {
                "servers": {"search": [("сервер", 100)]},
                "all_in_one_computers": {"search": [("моноблок", 100)]},
                "desktop_computers": {"search": [
                    ("системный блок", 100), ("персональная эвм", 100),
                    ("настольный компьютер", 100)]},
                "monitors": {"search": [("монитор", 100)]},
                "computer_peripherals": {"search": [
                    ("клавиатура", 100), ("мышь", 100)]},
            },
            "lighting": {},
        },
    )


def _resolve(category: str, title: str, **kwargs) -> r.Resolution:
    return r.resolve(
        r.ResolverInput(category_code=category, title=title, **kwargs), _ctx()
    )


def test_server_supply():
    assert _resolve("computers", "Поставка сервера").subcategory_code == "servers"


def test_monoblock_supply():
    res = _resolve("computers", "Поставка моноблоков")
    assert res.subcategory_code == "all_in_one_computers"


def test_lighting_poles():
    res = _resolve("lighting", "Опоры наружного освещения")
    assert res.subcategory_code == "lighting_poles"


def test_school_works_stay_unclassified():
    # 'Капремонт школы' must NOT become an OBJECT_CONTEXT or product node.
    assert _resolve("lighting", "Капремонт школы").subcategory_code is None
    assert _resolve("lighting", "Капремонт школы",
                    allow_term_match=False).subcategory_code is None


def test_sentinel_is_unclassified():
    assert r.is_unclassified("SUBCATEGORY_NOT_ASSIGNED") is True
    assert r.is_unclassified(None) is True
    assert r.is_unclassified("") is True
    assert r.is_unclassified("servers") is False


def test_pc_kit_prefers_workstation():
    res = _resolve(
        "computers",
        "Персональные ЭВМ: системный блок, клавиатура, мышь, монитор",
    )
    assert res.subcategory_code == "workstation_kits"


def test_keyboard_mouse_kit_is_peripherals():
    res = _resolve("computers", "Комплект клавиатура и мышь")
    assert res.subcategory_code == "computer_peripherals"
