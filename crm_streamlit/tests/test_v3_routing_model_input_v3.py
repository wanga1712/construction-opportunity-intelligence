"""Tests for V3_ROUTING_MODEL_INPUT_V3 contract."""
from __future__ import annotations

from src.services.commercial_routing_v3.model_input import (
    audit_model_input_required_fields,
    build_v3_routing_model_input,
    model_input_hash,
    model_input_json,
)
from src.services.commercial_routing_v3.prompt import build_v3_prompt_from_model_input


def _card(**over):
    base = {
        "procurement_id": 1,
        "procurement_number": "X",
        "source_contour": "PUBLIC_44FZ",
        "source_table": "reestr_contract_44fz",
        "source_id": 10,
        "source_origin": "FORWARD_NEW",
        "title": "Кабель силовой",
        "official_description": None,
        "normalized_lifecycle": "OPEN",
        "source_start_date": "2026-08-01",
        "source_end_date": "2026-08-20",
        "procurement_start_at": "2026-08-01",
        "procurement_end_at": "2026-08-20",
        "remaining_days": 6,
        "deadline_pressure": "MEDIUM",
        "source_delivery_start_date": "2026-09-01",
        "source_delivery_end_date": "2026-10-01",
        "delivery_start_at": "2026-09-01",
        "delivery_end_at": "2026-10-01",
        "customer_name": "ООО Заказчик",
        "customer_inn": "7700000000",
        "primary_commercial_region": "Москва",
        "primary_commercial_region_source": "SOURCE_DELIVERY_REGION",
        "okpd_code": "27.32.13.110",
        "okpd_name": "Кабели",
        "okpd": {"okpd_code": "27.32.13.110", "okpd_name": "Кабели", "hierarchy": []},
        "COMMERCIAL_PRODUCT_PRIORS": [],
        "CONTEXTUAL_RESEARCH_PRIORS": [
            {
                "category": "cable_support_systems",
                "okpd_pattern": "27.32",
                "weight": 1,
                "prior_kind": "CONTEXTUAL_RESEARCH_PRIOR",
            }
        ],
        "DIRECT_CABLE_EXPECTED_RESULT": "NO_COMMERCIAL_ENTRY",
        "source_card_url": "https://example",
        "source_card_url_type": "tender_link",
        "document_link_count": 3,
        "unique_document_url_count": 2,
        "document_links_summary": [{"name": "a", "url": "http://x"}] * 50,
        "initial_price": 1000,
    }
    base.update(over)
    return base


def test_model_input_excludes_document_blobs():
    mi = build_v3_routing_model_input(_card())
    blob = model_input_json(mi)
    assert "document_links_summary" not in mi
    assert "http://x" not in blob
    assert mi["model_input_version"] == "V3_ROUTING_MODEL_INPUT_V3"
    assert mi["okpd_codes"] == ["27.32.13.110"]
    assert mi["CONTEXTUAL_RESEARCH_PRIORS"]
    assert mi["COMMERCIAL_PRODUCT_PRIORS"] == []


def test_open_does_not_require_winner_or_final_price():
    mi = build_v3_routing_model_input(_card())
    assert mi.get("winner_name") in (None, "")
    assert mi.get("final_contract_price") in (None, "")
    miss = audit_model_input_required_fields(mi, source_row={"delivery_start_date": "2026-09-01"})
    assert miss["MODEL_INPUT_WITHOUT_WINNER_AWARDED"] == 0
    assert miss["MODEL_INPUT_WITHOUT_FINAL_PRICE_AWARDED"] == 0
    assert miss["OPEN_WINNER_NULL_OK"] == 1
    assert miss["OPEN_FINAL_PRICE_NULL_OK"] == 1
    assert miss["MODEL_INPUT_WITHOUT_INITIAL_PRICE"] == 0
    assert miss["MODEL_INPUT_WITHOUT_SOURCE_ORIGIN"] == 0


def test_awarded_requires_winner_when_source_has_winner():
    mi = build_v3_routing_model_input(
        _card(
            normalized_lifecycle="AWARDED",
            winner_name=None,
            final_contract_price=None,
            procurement_start_at=None,
            procurement_end_at=None,
        )
    )
    miss = audit_model_input_required_fields(
        mi,
        source_row={"winner_name": "ООО Победитель", "final_price": 900, "award_date": "2026-01-01"},
    )
    assert miss["MODEL_INPUT_WITHOUT_WINNER_AWARDED"] == 1
    assert miss["MODEL_INPUT_WITHOUT_FINAL_PRICE_AWARDED"] == 1



def test_prompt_uses_model_input_not_link_dump():
    mi = build_v3_routing_model_input(_card())
    prompt = build_v3_prompt_from_model_input(
        mi,
        registry=[{"category_code": "lighting", "category_name": "Lighting", "subcategories": []}],
        okpd_priors=[],
        procurement_form_prior="DIRECT_GOODS_PURCHASE",
    )
    assert "V3_ROUTING_MODEL_INPUT_V3" in prompt
    assert "COMMERCIAL_PRODUCT_PRIOR" in prompt
    assert "CONTEXTUAL_RESEARCH_PRIOR" in prompt
    assert "http://x" not in prompt
    h1 = model_input_hash(mi)
    h2 = model_input_hash(build_v3_routing_model_input(_card()))
    assert h1 == h2


def test_region_and_dates_separated():
    mi = build_v3_routing_model_input(_card())
    assert mi["primary_commercial_region"] == "Москва"
    assert mi["procurement_end_at"] == "2026-08-20"
    assert mi["delivery_end_at"] == "2026-10-01"
    assert mi["procurement_end_at"] != mi["delivery_end_at"]
