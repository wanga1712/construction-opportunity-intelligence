"""CRM-V3-OBJECT-MODE-CONSTRUCTION-DESIGN-ROUTING-1."""
from __future__ import annotations

import json
from pathlib import Path

from src.domain.commercial_taxonomy import COMMERCIAL_KEEP_CODES
from src.services.commercial_routing_v3.model_input import model_input_as_prompt_procurement
from src.services.commercial_routing_v3.normalizer import normalize_v3_output
from src.services.commercial_routing_v3.object_mode_routing import (
    classify_object,
    enrich_object_mode_routing,
    is_genuine_object_procurement,
)
from src.services.commercial_routing_v3.prompt import PROMPT_VERSION

ALLOWED = set(COMMERCIAL_KEEP_CODES)


def _load_frozen(pid: int) -> dict:
    p = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "v3_model_input"
    # Use inline minimal fixtures when frozen files absent locally.
    if pid == 10753:
        return {
            "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
            "procurement_id": 10753,
            "title": "Ликвидация деформаций и разрушений покрытия на автомобильной дороге общего пользования А-146 Адыгея",
            "okpd_codes": ["42.11"],
            "COMMERCIAL_PRODUCT_PRIORS": [],
            "CONTEXTUAL_RESEARCH_PRIORS": [
                {"category": "lighting", "okpd_pattern": "42.11", "weight": 50, "prior_kind": "CONTEXTUAL_RESEARCH_PRIOR"},
                {"category": "waterproofing", "okpd_pattern": "42.11", "weight": 50, "prior_kind": "CONTEXTUAL_RESEARCH_PRIOR"},
                {"category": "drainage_water_management", "okpd_pattern": "42.11", "weight": 50, "prior_kind": "CONTEXTUAL_RESEARCH_PRIOR"},
                {"category": "curbstone", "okpd_pattern": "42.11", "weight": 35, "prior_kind": "CONTEXTUAL_RESEARCH_PRIOR"},
                {"category": "composite_structures", "okpd_pattern": "42.11", "weight": 35, "prior_kind": "CONTEXTUAL_RESEARCH_PRIOR"},
            ],
        }
    if pid == 18215:
        return {
            "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
            "procurement_id": 18215,
            "title": "Поставка счетчиков газа и комплектующих производства ООО «Техномер»",
            "okpd_codes": ["26.51.63.110"],
            "COMMERCIAL_PRODUCT_PRIORS": [],
            "CONTEXTUAL_RESEARCH_PRIORS": [],
        }
    if pid == 17141:
        return {
            "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
            "procurement_id": 17141,
            "title": "Аренда, монтаж, демонтаж временных ограждений",
            "okpd_codes": ["43.99"],
            "COMMERCIAL_PRODUCT_PRIORS": [],
            "CONTEXTUAL_RESEARCH_PRIORS": [],
        }
    raise KeyError(pid)


def _proc(pid: int) -> dict:
    mi = _load_frozen(pid)
    shaped = model_input_as_prompt_procurement(mi)
    shaped["v3_model_input"] = mi
    return shaped


def test_prompt_version_v5() -> None:
    assert PROMPT_VERSION == "v3_category_centric_routing_7b_v5"


def test_18215_direct_goods_nce_unchanged() -> None:
    proc = _proc(18215)
    raw = {
        "procurement_form": "DIRECT_GOODS_PURCHASE",
        "commercial_category_hypotheses": [],
        "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
        "overall_research_action": "SKIP",
    }
    out = enrich_object_mode_routing(
        normalize_v3_output(raw, allowed_categories=ALLOWED, allowed_subcategories={}, has_okpd=True),
        proc,
        allowed_categories=ALLOWED,
    )
    assert out["empty_hypothesis_status"] == "NO_COMMERCIAL_ENTRY"
    assert out["overall_research_action"] == "SKIP"
    assert out.get("routing_mode") != "OBJECT_MODE"


def test_17141_rental_not_object_target() -> None:
    proc = _proc(17141)
    genuine, _ = is_genuine_object_procurement(proc, form="CONSTRUCTION_WORKS")
    assert genuine is False
    raw = {
        "procurement_form": "CONSTRUCTION_WORKS",
        "commercial_category_hypotheses": [],
        "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
        "overall_research_action": "SKIP",
    }
    out = enrich_object_mode_routing(
        normalize_v3_output(raw, allowed_categories=ALLOWED, allowed_subcategories={}, has_okpd=True),
        proc,
        allowed_categories=ALLOWED,
    )
    assert out["empty_hypothesis_status"] == "NO_COMMERCIAL_ENTRY"
    assert not out.get("commercial_category_hypotheses")


def test_10753_object_mode_blocks_mistaken_nce() -> None:
    proc = _proc(10753)
    obj = classify_object(proc, form="CONSTRUCTION_WORKS")
    assert obj["object_sector"] == "TRANSPORT_INFRASTRUCTURE"
    assert obj["object_type"] == "ROAD"
    assert "REPAIR" in obj["object_context"] or obj["work_stage"] == "REPAIR"

    raw = {
        "procurement_form": "CONSTRUCTION_WORKS",
        "commercial_category_hypotheses": [],
        "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
        "overall_research_action": "SKIP",
    }
    out = enrich_object_mode_routing(
        normalize_v3_output(raw, allowed_categories=ALLOWED, allowed_subcategories={}, has_okpd=True),
        proc,
        allowed_categories=ALLOWED,
    )
    assert out["routing_mode"] == "OBJECT_MODE"
    # Phase 6B: MODEL empty status stays; business clears mistaken NCE via priors.
    assert out.get("empty_hypothesis_status") == "NO_COMMERCIAL_ENTRY"
    assert out.get("business_empty_hypothesis_status") is None
    assert out.get("business_overall_research_action") != "SKIP"
    assert out["commercial_category_hypotheses"] == []  # MODEL hyps unchanged (empty)
    hyps = out.get("business_category_hypotheses") or out.get("contextual_prior_hypotheses") or []
    assert len(hyps) >= 2
    cats = {h["category_code"] for h in hyps}
    assert cats <= ALLOWED
    assert "42.11" not in cats
    for h in hyps:
        assert h.get("evidence_role") == "CONTEXTUAL_RESEARCH_PRIOR"
        assert h.get("confirmation_required") is True
        assert h.get("opportunity_track") == "EMBEDDED_MATERIAL"
        assert "requires_document_confirmation" in (h.get("reason_codes") or [])
        assert h.get("provenance") == "CONTEXT_PRIOR"
    assert out.get("DOCUMENT_RESEARCH_REQUIRED") is True
    assert out.get("business_document_research_priority") or out.get("document_research_priority")


def test_20228_awarded_school_capital_repair_coercion() -> None:
    mi = {
        "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
        "procurement_id": 20228,
        "title": 'Капитальный ремонт здания МКОУ "Средняя общеобразовательная школа №6"',
        "okpd_codes": ["41.20.40.900"],
        "normalized_lifecycle": "AWARDED",
        "winner_name": 'ООО "ТРАСТ ПРОЕКТ"',
        "final_contract_price": 99519243.34,
        "delivery_start_at": "2026-01-16",
        "delivery_end_at": "2026-08-31",
        "COMMERCIAL_PRODUCT_PRIORS": [],
        "CONTEXTUAL_RESEARCH_PRIORS": [
            {"category": "flooring", "okpd_pattern": "41.20", "weight": 50, "prior_kind": "CONTEXTUAL_RESEARCH_PRIOR"},
            {"category": "waterproofing", "okpd_pattern": "41.20", "weight": 50, "prior_kind": "CONTEXTUAL_RESEARCH_PRIOR"},
        ],
    }
    proc = model_input_as_prompt_procurement(mi)
    proc["v3_model_input"] = mi
    raw = {
        "procurement_form": "DIRECT_GOODS_PURCHASE",
        "commercial_category_hypotheses": [
            {"category_code": "41.20.40.900", "opportunity_track": "DIRECT_SUPPLY", "confidence": 0.5}
        ],
        "empty_hypothesis_status": "REVIEW_REQUIRED",
        "overall_research_action": "DISCOVER_COMMERCIAL_CATEGORY",
    }
    out = enrich_object_mode_routing(
        normalize_v3_output(raw, allowed_categories=ALLOWED, allowed_subcategories={}, has_okpd=True),
        proc,
        allowed_categories=ALLOWED,
    )
    assert out["routing_mode"] == "OBJECT_MODE"
    # Phase 6B: MODEL form preserved; coercion lives in business_procurement_form.
    assert out["procurement_form"] == "DIRECT_GOODS_PURCHASE"
    assert out.get("business_procurement_form") == "CONSTRUCTION_WORKS"
    assert out.get("post_award_commercial_target") == "WINNER_CONTRACTOR"
    assert "ТРАСТ" in str(out.get("post_award_commercial_target_name") or "").upper()
    # MODEL object_classification may be absent on this raw; business classification holds school.
    obj = out.get("business_object_classification") or out["object_classification"]
    assert obj["object_sector"] == "SOCIAL_INFRASTRUCTURE"
    assert obj["object_type"] == "SCHOOL"
    assert obj["work_stage"] == "CAPITAL_REPAIR"
    hyps = out.get("business_category_hypotheses") or out["commercial_category_hypotheses"]
    assert len(hyps) >= 1
    assert (
        out.get("business_overall_research_action") or out["overall_research_action"]
    ) == "PRIORITY_DOCS"


def test_10753_no_direct_supply_from_contextual() -> None:
    proc = _proc(10753)
    raw = {
        "procurement_form": "CONSTRUCTION_WORKS",
        "commercial_category_hypotheses": [
            {
                "category_code": "lighting",
                "opportunity_track": "DIRECT_SUPPLY",
                "confidence": 0.8,
                "reason_codes": ["okpd_match"],
            }
        ],
    }
    out = enrich_object_mode_routing(
        normalize_v3_output(raw, allowed_categories=ALLOWED, allowed_subcategories={}, has_okpd=True),
        proc,
        allowed_categories=ALLOWED,
    )
    for h in out["commercial_category_hypotheses"]:
        assert h["opportunity_track"] != "DIRECT_SUPPLY"
