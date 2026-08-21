"""Phase 9 contract tests — full registry payload + validator subject/candidates."""
from __future__ import annotations

from src.services.commercial_routing_v3.model_result_validator import validate_model_result
from src.services.commercial_routing_v3.prompt import PROMPT_VERSION as PROD_PROMPT
from src.services.commercial_routing_v3.prompt_v9_full_registry import (
    PROMPT_VERSION as V9,
    build_v9_prompt_from_model_input,
)
from src.services.commercial_routing_v3.registry_prompt_payload import (
    PAINT_SHADOW_CATEGORY,
    SUBCATEGORY_ARCHITECTURE,
    build_active_registry_payload,
)


def test_production_prompt_unchanged():
    assert PROD_PROMPT == "v3_category_centric_routing_7b_v5"
    assert V9 != PROD_PROMPT
    assert "full_registry" in V9


def test_full_registry_payload_includes_all_and_shadow_paint():
    rows = [
        {"category_code": "computers", "category_name": "ПК", "description": "компьютеры"},
        {"category_code": "lighting", "category_name": "Свет", "aliases": ["светильник"]},
    ]
    payload, codes = build_active_registry_payload(
        rows, extra_shadow_categories=[PAINT_SHADOW_CATEGORY]
    )
    assert codes == ["computers", "lighting", "paint"]
    assert all(p["category_code"] in codes for p in payload)
    paint = next(p for p in payload if p["category_code"] == "paint")
    assert paint.get("shadow_extension") is True


def test_v9_prompt_lists_every_active_code_without_title_filter():
    mi = {
        "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
        "title": "Поставка краски",
        "okpd_codes": ["20.30"],
        "okpd_names": ["Краски"],
        "COMMERCIAL_PRODUCT_PRIORS": [],
        "CONTEXTUAL_RESEARCH_PRIORS": [],
    }
    registry = [
        {"category_code": "computers", "category_name": "ПК"},
        {"category_code": "drainage_water_management", "category_name": "Дренаж"},
        {"category_code": "lighting", "category_name": "Свет"},
    ]
    prompt = build_v9_prompt_from_model_input(
        mi,
        registry=registry,
        okpd_priors=[],
        procurement_form_prior="DIRECT_GOODS_PURCHASE",
        extra_shadow_categories=[PAINT_SHADOW_CATEGORY],
    )
    assert "computers" in prompt
    assert "drainage_water_management" in prompt
    assert "lighting" in prompt
    assert "paint" in prompt
    assert "subject_interpretation" in prompt
    assert "research_priority" in prompt
    assert SUBCATEGORY_ARCHITECTURE in prompt
    # No forced object spam instruction
    assert "Emit ZERO candidates when no registry" in prompt


def test_validator_maps_candidates_and_keeps_subject():
    parsed = {
        "procurement_form": "DIRECT_GOODS_PURCHASE",
        "subject_interpretation": {
            "subject_type": "GOODS",
            "normalized_subject": "персональный настольный компьютер / моноблок",
        },
        "commercial_category_candidates": [
            {
                "category_code": "computers",
                "candidate_role": "DIRECT_PURCHASE",
                "research_priority": "HIGH",
                "confirmation_required": False,
            }
        ],
        "commercial_category_hypotheses": [],
        "analysis_modes": ["DIRECT_PRODUCT"],
        "empty_hypothesis_status": None,
        "overall_research_action": "LIGHT_RESEARCH",
        "object_classification": {"object_type": "GOODS", "work_stage": "SUPPLY"},
        "document_research_priority": [],
        "material_signals": [],
        "work_methods": [],
        "application_areas": [],
        "brands": [],
        "object_context": [],
    }
    res = validate_model_result(parsed, allowed_categories={"computers", "lighting"})
    assert res.status == "VALIDATED_SUCCESS"
    assert res.validated is not None
    assert res.validated["subject_interpretation"]["normalized_subject"].startswith("персональный")
    hyps = res.validated["commercial_category_hypotheses"]
    assert len(hyps) == 1
    assert hyps[0]["category_code"] == "computers"
    assert hyps[0]["research_priority"] == "HIGH"


def test_validator_rejects_invented_code_keeps_subject():
    parsed = {
        "procurement_form": "DIRECT_GOODS_PURCHASE",
        "subject_interpretation": {
            "subject_type": "GOODS",
            "normalized_subject": "кабель",
        },
        "commercial_category_candidates": [
            {"category_code": "cable", "candidate_role": "DIRECT_PURCHASE", "research_priority": "HIGH"}
        ],
        "analysis_modes": ["DIRECT_PRODUCT"],
        "empty_hypothesis_status": None,
        "overall_research_action": "LIGHT_RESEARCH",
        "material_signals": [],
        "work_methods": [],
        "application_areas": [],
        "brands": [],
        "object_context": [],
    }
    res = validate_model_result(parsed, allowed_categories={"computers", "drainage_water_management"})
    assert res.validated is not None
    assert res.validated["commercial_category_hypotheses"] == []
    assert res.validated["subject_interpretation"]["normalized_subject"] == "кабель"
    assert any("rejected_category_not_in_registry:cable" in e for e in res.errors)


def test_validator_allows_abstention_empty_candidates():
    parsed = {
        "procurement_form": "CONSTRUCTION_WORKS",
        "subject_interpretation": {
            "subject_type": "OBJECT_WORKS",
            "object_type": "ROAD",
            "work_stage": "REPAIR",
        },
        "commercial_category_candidates": [],
        "commercial_category_hypotheses": [],
        "empty_hypothesis_status": "INSUFFICIENT_EVIDENCE",
        "overall_research_action": "LIGHT_RESEARCH",
        "analysis_modes": ["EMBEDDED_MATERIAL_DISCOVERY"],
        "material_signals": [],
        "work_methods": [],
        "application_areas": [],
        "brands": [],
        "object_context": [],
    }
    res = validate_model_result(parsed, allowed_categories={"curbstone", "lighting"})
    assert res.status == "VALIDATED_SUCCESS"
    assert res.validated["commercial_category_hypotheses"] == []
    assert res.validated["empty_hypothesis_status"] == "INSUFFICIENT_EVIDENCE"
