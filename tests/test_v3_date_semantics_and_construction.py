"""Date semantics: published_at must not be fabricated from start_date."""
from __future__ import annotations

from src.services.commercial_routing_v3.canonical_card import build_canonical_card
from src.services.commercial_routing_v3.commercial_timing import (
    compute_active_commercial_timing,
)
from src.services.commercial_routing_v3.construction_semantics import (
    is_genuine_construction_object,
)
from datetime import date


def test_open_published_at_not_from_start_date():
    card = build_canonical_card(
        procurement={
            "id": 17141,
            "auction_name": "Аренда (монтаж, демонтаж) имущества (временные ограждения)",
            "source_table": "reestr_contract_223fz",
            "source_id": 1,
            "crm_stage": "active",
            "award_status": "",
            "start_date": "2026-08-25",
            "end_date": "2026-10-01",
            "source_created_at": "2026-07-29",
            "okpd_code": "43.29.12.110",
            "customer": "ООО Тест",
            "initial_price": 100,
            "delivery_region": "регион",
            "tender_link": "https://example",
        },
        priors=[],
        resolve_links=False,
    )
    assert card["published_at"] is None
    assert card["published_at_provenance"] == "SOURCE_NOT_AVAILABLE"
    assert card["source_start_date"] == "2026-08-25"
    assert card["procurement_start_at"] == "2026-08-25"
    assert "start_date" in (card["procurement_start_at_provenance"] or "")
    assert "PROCEDURE" in (card["procurement_start_at_provenance"] or "")
    assert card["source_created_at"] == "2026-07-29"
    assert card["source_created_at_role"] == "INGESTION_OR_SOURCE_PRESENCE_ONLY"


def test_rental_fence_not_genuine_construction():
    ok, reason = is_genuine_construction_object(
        title="Аренда (монтаж, демонтаж) имущества (временные ограждения)",
        okpd_codes=["43.29.12.110"],
    )
    assert ok is False
    assert "NEGATIVE" in reason or "NO_CONSTRUCTION" in reason


def test_road_asphalt_is_genuine_construction():
    ok, reason = is_genuine_construction_object(
        title="Асфальтирование части дороги ул. Тарловская",
        okpd_codes=["42.11"],
    )
    assert ok is True


def test_future_start_does_not_max_freshness():
    t = compute_active_commercial_timing(
        procurement_start_at="2026-08-25",
        procurement_end_at="2026-10-01",
        source_created_at="2026-07-29",
        published_at=None,
        published_at_provenance="SOURCE_NOT_AVAILABLE",
        as_of=date(2026, 8, 14),
    )
    assert t["commercial_timing_confidence"].startswith(("REDUCED", "AMBIGUOUS", "LOW"))
    # Must not behave as age=0 max freshness from future start clamp
    assert t["commercial_timing_components"]["freshness"] <= 0.45
