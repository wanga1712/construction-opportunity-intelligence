"""Phase 6B — semantic namespace separation tests."""
from __future__ import annotations

import copy
from typing import Any, Dict

from src.services.commercial_routing_v3.field_provenance import (
    BUSINESS_RULE,
    MODEL_DERIVED,
    MODEL_VALIDATED,
    UNKNOWN_LEGACY,
    build_field_provenance,
)
from src.services.commercial_routing_v3.model_ui_projection import (
    business_view_from_assessment,
    model_view_from_assessment,
)
from src.services.commercial_routing_v3.object_mode_routing import enrich_object_mode_routing
from src.services.commercial_routing_v3.routing_outcome import model_derived_overall_confidence


ALLOWED = {"lighting", "waterproofing", "drainage_water_management", "computers"}


def _model_payload(**over) -> Dict[str, Any]:
    row = {
        "source_contour": "PUBLIC_44FZ",
        "procurement_form": "CONSTRUCTION_WORKS",
        "analysis_modes": ["OBJECT_CONTEXT"],
        "object_context": [],
        "material_signals": [],
        "work_methods": [],
        "application_areas": [],
        "brands": [],
        "commercial_category_hypotheses": [
            {
                "category_code": "waterproofing",
                "opportunity_track": "EMBEDDED_MATERIAL",
                "confidence": 0.0,
                "research_action": "LIGHT_RESEARCH",
                "reason_codes": ["model_said"],
            }
        ],
        "object_classification": {
            "object_sector": "CONSTRUCTION",
            "object_type": "BUILDINGS",
            "object_subtype": "SCHOOL",
            "object_context": [],
            "work_stage": "CAPITAL_REPAIR",
        },
        "empty_hypothesis_status": None,
        "preferred_opportunity_track": None,
        "empty_hypothesis_reason_codes": [],
        "discovery_required": False,
        "overall_research_action": "LIGHT_RESEARCH",
        "document_research_priority": [],
    }
    row.update(over)
    return row


def test_enrich_does_not_overwrite_model_object_classification() -> None:
    model = _model_payload()
    before = copy.deepcopy(model["object_classification"])
    procurement = {
        "title": "Капитальный ремонт здания школы",
        "okpd_code": "41.20.10",
        "procurement_form": "CONSTRUCTION_WORKS",
        "v3_model_input": {
            "title": "Капитальный ремонт здания школы",
            "okpd_codes": ["41.20.10"],
            "CONTEXTUAL_RESEARCH_PRIORS": [
                {"category_code": "drainage_water_management", "track": "EMBEDDED_MATERIAL"}
            ],
        },
    }
    out = enrich_object_mode_routing(model, procurement, allowed_categories=ALLOWED)
    assert out["object_classification"] == before
    assert out.get("business_object_classification") is not None
    assert out["object_classification"]["object_type"] == "BUILDINGS"


def test_enrich_does_not_overwrite_model_subtype_or_stage() -> None:
    model = _model_payload()
    out = enrich_object_mode_routing(
        model,
        {
            "title": "Ремонт автомобильной дороги",
            "okpd_code": "42.11.10",
            "procurement_form": "CONSTRUCTION_WORKS",
            "v3_model_input": {"title": "Ремонт автомобильной дороги", "okpd_codes": ["42.11.10"]},
        },
        allowed_categories=ALLOWED,
    )
    assert out["object_classification"]["object_subtype"] == "SCHOOL"
    assert out["object_classification"]["work_stage"] == "CAPITAL_REPAIR"


def test_enrich_preserves_model_procurement_form() -> None:
    model = _model_payload(procurement_form="DIRECT_GOODS_PURCHASE")
    # Strong object title may coerce business form but must not replace MODEL form.
    out = enrich_object_mode_routing(
        model,
        {
            "title": "Капитальный ремонт здания школы",
            "okpd_code": "41.20.10",
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "v3_model_input": {
                "title": "Капитальный ремонт здания школы",
                "okpd_codes": ["41.20.10"],
            },
        },
        allowed_categories=ALLOWED,
    )
    assert out["procurement_form"] == "DIRECT_GOODS_PURCHASE"


def test_contextual_prior_not_in_model_hypotheses() -> None:
    model = _model_payload(commercial_category_hypotheses=[], empty_hypothesis_status="NO_COMMERCIAL_ENTRY")
    out = enrich_object_mode_routing(
        model,
        {
            "title": "Капитальный ремонт здания школы",
            "okpd_code": "41.20.10",
            "procurement_form": "CONSTRUCTION_WORKS",
            "v3_model_input": {
                "title": "Капитальный ремонт здания школы",
                "okpd_codes": ["41.20.10"],
                "CONTEXTUAL_RESEARCH_PRIORS": [
                    {"category_code": "drainage_water_management"}
                ],
            },
        },
        allowed_categories=ALLOWED,
    )
    assert out["commercial_category_hypotheses"] == []
    priors = out.get("contextual_prior_hypotheses") or []
    assert isinstance(priors, list)
    # Business may have priors; MODEL list stays empty.
    for h in out["commercial_category_hypotheses"]:
        assert "object_mode_contextual_prior" not in (h.get("reason_codes") or [])


def test_zero_confidence_preserved_model_derived() -> None:
    model = _model_payload()
    assert model_derived_overall_confidence(model) == 0.0


def test_missing_confidence_not_100() -> None:
    model = _model_payload(commercial_category_hypotheses=[{"category_code": "lighting", "opportunity_track": "DIRECT_SUPPLY"}])
    assert model_derived_overall_confidence(model) is None


def test_ui_model_uses_validated_not_normalized() -> None:
    assessment = {
        "inference_run_id": 42,
        "model_provenance": "MODEL_VALIDATED",
        "validated_model_result": {
            "procurement_form": "CONSTRUCTION_WORKS",
            "object_classification": {
                "object_type": "ROADS_AND_AUTOMOBILE_HIGHWAYS",
                "object_subtype": "ROAD",
                "work_stage": "MAINTENANCE",
            },
            "commercial_category_hypotheses": [
                {
                    "category_code": "waterproofing",
                    "confidence": 0.4,
                    "opportunity_track": "EMBEDDED_MATERIAL",
                }
            ],
        },
        "normalized_result": {
            "route_profile": "CONSTRUCTION_INFRASTRUCTURE",
            "business_scope_status": "IN_PROFILE",
            "candidate_level": "GOLD",
            "candidate_score": 99,
            "category_opportunities": [
                {
                    "category_code": "drainage_water_management",
                    "reason_codes": ["object_mode_contextual_prior"],
                    "confidence": 0.9,
                }
            ],
        },
    }
    view = model_view_from_assessment(assessment)
    assert view["provenance"] == "MODEL_VALIDATED"
    assert view["object_type"] == "ROADS_AND_AUTOMOBILE_HIGHWAYS"
    assert view["hypotheses"][0]["category"] == "waterproofing"
    assert view["contains_rule_fields"] is False
    # Contextual prior must not appear in model view
    cats = [h["category"] for h in view["hypotheses"]]
    assert "drainage_water_management" not in cats
    assert view["overall_confidence_provenance"] == "MODEL_DERIVED"


def test_legacy_ui_not_labeled_model() -> None:
    assessment = {
        "inference_run_id": None,
        "normalized_result": {
            "category_opportunities": [{"category_code": "lighting", "confidence": 0.8}],
            "procurement_form": "DIRECT_GOODS_PURCHASE",
        },
    }
    view = model_view_from_assessment(assessment)
    assert view["provenance"] == "UNKNOWN_LEGACY"
    assert "не сохранён" in (view.get("label") or "")


def test_business_view_not_model() -> None:
    assessment = {
        "business_rule_result": {
            "route_profile": "CONSTRUCTION_BUILDING",
            "business_scope_status": "OUT_OF_PROFILE",
            "business_candidate_medal": "SILVER",
            "business_candidate_score": 55.0,
            "effective_medal": "BRONZE",
        }
    }
    biz = business_view_from_assessment(assessment)
    assert biz["provenance"] == "BUSINESS_RULE"
    assert biz["route_profile"] == "CONSTRUCTION_BUILDING"
    assert biz["business_candidate_medal"] == "SILVER"
    assert biz["effective_medal"] == "BRONZE"


def test_field_provenance_matrix() -> None:
    fp = build_field_provenance(
        model_validated=_model_payload(),
        has_inference_run=True,
        overall_confidence_source=MODEL_DERIVED,
    )
    assert fp["object_type"] == MODEL_VALIDATED
    assert fp["route_profile"] == BUSINESS_RULE
    assert fp["business_scope_status"] == BUSINESS_RULE
    assert fp["candidate_score"] == BUSINESS_RULE
    assert fp["candidate_medal"] == BUSINESS_RULE
    assert fp["overall_confidence"] == MODEL_DERIVED
    legacy = build_field_provenance(has_inference_run=False)
    assert legacy["object_type"] == UNKNOWN_LEGACY


def test_model_validated_not_mutated_by_enrich_input() -> None:
    model = _model_payload()
    original = copy.deepcopy(model)
    enrich_object_mode_routing(
        model,
        {
            "title": "Капитальный ремонт здания школы",
            "okpd_code": "41.20.10",
            "procurement_form": "CONSTRUCTION_WORKS",
            "v3_model_input": {"title": "Капитальный ремонт здания школы", "okpd_codes": ["41.20.10"]},
        },
        allowed_categories=ALLOWED,
    )
    assert model == original
