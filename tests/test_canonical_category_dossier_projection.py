from __future__ import annotations

from pathlib import Path

from src.services import procurement_card_dossier_service as dossier_service
from src.services.procurement_card_category_service import build_category_cards


def _opp(**overrides):
    row = {
        "commercial_category_code": "composite_structures",
        "commercial_subcategory_code": "SUBCATEGORY_NOT_ASSIGNED",
        "opportunity_track": "EMBEDDED_MATERIAL",
        "status": "CURRENT",
        "candidate_initial_medal": "SILVER",
        "confirmed_base_medal": None,
        "current_effective_medal": "BRONZE",
        "expected_category_value": 1234.0,
        "category_value_basis": "EXISTING_ACCEPTED_VALUE",
        "commercial_state": "ACTIVE",
        "category_name": "Композитные конструкции",
    }
    row.update(overrides)
    return row


def _position(**overrides):
    row = {
        "structured_entity_id": 10,
        "category_code": "composite_structures",
        "subcategory_code": None,
        "product_name_raw": "Исходное имя строки",
        "product_name_normalized": "Нормализованное имя",
        "quantity": 2,
        "unit": "шт",
        "unit_price": None,
        "total": None,
        "section_code": "RESIDUE",
        "trust_state": "MANUAL_PROOF_QUARANTINE",
        "source_document_id": 5,
        "row_or_line": "12",
        "has_quantity": True,
        "has_unit": True,
        "has_unit_price": False,
        "has_total": False,
        "full_quartet": False,
    }
    row.update(overrides)
    return row


def _build(opportunities, positions):
    return build_category_cards(
        opportunities=opportunities,
        supply_facts=[],
        category_positions=positions,
        documents=[],
        queue_progress={},
        procurement_id=60467,
        model_counts={},
        extraction_outcomes={},
    )


def test_current_opportunity_without_positions_still_has_category_card():
    cards = _build([_opp()], [])

    assert len(cards) == 1
    assert cards[0]["category_code"] == "composite_structures"
    assert cards[0]["position_count"] == 0
    assert cards[0]["commercial_value"] == 1234.0


def test_each_current_opportunity_creates_one_card_even_when_all_are_empty():
    opportunities = [
        _opp(commercial_category_code=code, commercial_subcategory_code=None)
        for code in (
            "composite_structures", "curbstone", "drainage_water_management",
            "lighting", "waterproofing",
        )
    ]
    cards = _build(opportunities, [])

    assert len(cards) == len(opportunities) == 5
    assert {card["category_code"] for card in cards} == {
        "composite_structures", "curbstone", "drainage_water_management",
        "lighting", "waterproofing",
    }


def test_incomplete_category_position_remains_visible_and_residue_stays_assigned():
    position = _position()
    cards = _build([_opp()], [position])

    assert len(cards) == 1
    assert len(cards[0]["positions"]) == 1
    assert cards[0]["positions"][0]["structured_entity_id"] == position["structured_entity_id"]
    assert cards[0]["positions"][0]["full_quartet"] is False
    assert cards[0]["positions"][0]["section_code"] == "RESIDUE"
    assert cards[0]["category_code"] == "composite_structures"


def test_category_isolation_and_same_name_different_source_rows_are_preserved():
    first = _position(structured_entity_id=10, row_or_line="12")
    repeated = _position(structured_entity_id=11, row_or_line="18")
    foreign = _position(
        structured_entity_id=12,
        category_code="lighting",
        row_or_line="19",
    )
    cards = _build([_opp()], [first, repeated, foreign])

    assert cards[0]["position_count"] == 2
    assert [p["row_or_line"] for p in cards[0]["positions"]] == ["12", "18"]
    assert all(p["category_code"] == "composite_structures" for p in cards[0]["positions"])


def test_authoritative_value_is_taken_from_opportunity_not_position_sum():
    position = _position(total=999999.0)
    cards = _build([_opp(expected_category_value=321.0)], [position])

    assert cards[0]["commercial_value"] == 321.0
    assert cards[0]["commercial_value_basis"] == "EXISTING_ACCEPTED_VALUE"


def test_confirmed_positions_require_accepted_trust_cohort():
    confirmed = _position(structured_entity_id=20, trust_state="SECTION_CONFIRMED")
    quarantined = _position(structured_entity_id=21, trust_state="MANUAL_PROOF_QUARANTINE")
    cards = _build([_opp()], [confirmed, quarantined])

    assert [p["structured_entity_id"] for p in cards[0]["confirmed_positions"]] == [20]


def test_true_unknown_category_is_the_only_unassigned_category_state():
    assert dossier_service.is_true_unassigned_category(None)
    assert dossier_service.is_true_unassigned_category("")
    assert dossier_service.is_true_unassigned_category("unknown")
    assert not dossier_service.is_true_unassigned_category("composite_structures")
    assert not dossier_service.is_true_unassigned_category("lighting")


def test_assigned_position_without_current_opportunity_is_not_unassigned_or_lost():
    orphan = _position(structured_entity_id=30, category_code="flooring")
    cards = _build([_opp()], [_position(structured_entity_id=31)])

    remaining = dossier_service.positions_without_current_opportunity(
        [orphan], cards
    )
    assert remaining == [orphan]
    assert not dossier_service.is_true_unassigned_category(orphan["category_code"])


def test_category_position_loader_keeps_existing_physical_row_stale_preference(monkeypatch):
    seen = {}

    def fake_safe_di(sql, params, errors=None, label="documents"):
        seen["sql"] = sql
        seen["params"] = params
        return []

    monkeypatch.setattr(dossier_service, "_safe_di", fake_safe_di)
    assert dossier_service.load_category_positions(60467) == []
    assert seen["params"] == (60467,)
    assert "PARTITION BY se.procurement_id, se.source_document_id" in seen["sql"]
    assert "coalesce(se.row_or_line, '')" in seen["sql"]
    assert "ORDER BY (se.section_code IS NOT NULL) DESC, se.id DESC" in seen["sql"]


def test_ui_displays_authoritative_category_value_without_summarizer():
    ui_path = Path(__file__).parents[1] / "src" / "ui" / "procurement_card_page.py"
    source = ui_path.read_text(encoding="utf-8")
    assert "summarize_category_cards(" not in source
    assert 'summary.get("commercial_value")' in source
