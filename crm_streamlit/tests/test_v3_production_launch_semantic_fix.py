"""CRM-V3-PRODUCTION-LAUNCH-SEMANTIC-FIX-AND-FRESH-100-CANARY-1 deterministic gates."""
from __future__ import annotations

from src.domain.commercial_taxonomy import COMMERCIAL_KEEP_CODES
from src.services.commercial_routing_v3.direct_product_evidence import (
    DIRECT_SUPPLY_REQUIRES_DIRECT_PRODUCT_EVIDENCE,
    collect_direct_product_evidence_sources,
    enforce_direct_supply_product_evidence,
)
from src.services.commercial_routing_v3.model_input import model_input_as_prompt_procurement
from src.services.commercial_routing_v3.normalizer import normalize_v3_output
from src.services.commercial_routing_v3.object_mode_routing import (
    classify_object,
    enrich_object_mode_routing,
)
from src.services.commercial_routing_v3.procurement_form import (
    strong_direct_goods_evidence,
    strong_object_procurement_evidence,
)
from src.services.commercial_routing_v3.prompt import (
    PROMPT_VERSION,
    _OBJECT_MODE_CONTRACT,
    build_v3_prompt_from_model_input,
)

ALLOWED = set(COMMERCIAL_KEEP_CODES)


def _proc(mi: dict) -> dict:
    shaped = model_input_as_prompt_procurement(mi)
    shaped["v3_model_input"] = mi
    shaped["title"] = mi.get("title")
    shaped["okpd_code"] = (mi.get("okpd_codes") or [None])[0]
    return shaped


def _run(raw: dict, proc: dict) -> dict:
    """Enrich then expose BUSINESS working view (tests assert pipeline semantics).

    MODEL authority fields remain on the enrich output under their original keys
    and are also mirrored under ``_model`` for Phase 6B assertions.
    """
    out = enrich_object_mode_routing(
        normalize_v3_output(
            raw, allowed_categories=ALLOWED, allowed_subcategories={}, has_okpd=True
        ),
        proc,
        allowed_categories=ALLOWED,
    )
    view = dict(out)
    view["_model"] = {
        "procurement_form": out.get("procurement_form"),
        "commercial_category_hypotheses": list(out.get("commercial_category_hypotheses") or []),
        "object_classification": out.get("object_classification"),
        "empty_hypothesis_status": out.get("empty_hypothesis_status"),
        "overall_research_action": out.get("overall_research_action"),
    }
    if out.get("business_procurement_form"):
        view["procurement_form"] = out["business_procurement_form"]
    if out.get("business_category_hypotheses") is not None:
        view["commercial_category_hypotheses"] = list(out["business_category_hypotheses"])
    if out.get("business_object_classification") is not None:
        view["object_classification"] = out["business_object_classification"]
    if out.get("business_overall_research_action"):
        view["overall_research_action"] = out["business_overall_research_action"]
    if "business_empty_hypothesis_status" in out:
        view["empty_hypothesis_status"] = out.get("business_empty_hypothesis_status")
    if out.get("business_document_research_priority"):
        view["document_research_priority"] = out["business_document_research_priority"]
    return view


def _mi_17723() -> dict:
    return {
        "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
        "procurement_id": 17723,
        "title": "Поставка сетевого оборудования",
        "okpd_codes": ["26.30.11.122"],
        "COMMERCIAL_PRODUCT_PRIORS": [],
        "CONTEXTUAL_RESEARCH_PRIORS": [
            {
                "category": "cable_support_systems",
                "okpd_pattern": "26.30",
                "prior_kind": "CONTEXTUAL_RESEARCH_PRIOR",
            }
        ],
    }


def _mi_18434() -> dict:
    return {
        "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
        "procurement_id": 18434,
        "title": "Поставка выключателей силовых высоковольтных (вакуумных, элегазовых, реклоузеров)",
        "okpd_codes": ["27.12.10.190"],
        "COMMERCIAL_PRODUCT_PRIORS": [],
        "CONTEXTUAL_RESEARCH_PRIORS": [
            {
                "category": "lighting",
                "okpd_pattern": "27.12",
                "prior_kind": "CONTEXTUAL_RESEARCH_PRIOR",
            }
        ],
    }


def _mi_17443() -> dict:
    return {
        "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
        "procurement_id": 17443,
        "title": "Право заключения договора по ОКПД 27.11.41 Поставка трансформаторов 25000кВА для нужд филиала",
        "okpd_codes": ["27.11.41"],
        "COMMERCIAL_PRODUCT_PRIORS": [],
        "CONTEXTUAL_RESEARCH_PRIORS": [],
    }


def test_prompt_v5_contextual_not_purchased_product() -> None:
    assert PROMPT_VERSION == "v3_category_centric_routing_7b_v5"
    text = build_v3_prompt_from_model_input(
        _mi_17723(),
        registry=[{"category_code": "computers", "category_name": "Computers"}],
        okpd_priors=[],
        procurement_form_prior="DIRECT_GOODS_PURCHASE",
    )
    assert "CONTEXTUAL_RESEARCH_PRIOR" in text
    assert "does NOT mean the purchased product" in text
    assert "NEVER convert CONTEXTUAL_RESEARCH_PRIOR into DIRECT_SUPPLY" in text
    assert "ALLOWED_COMMERCIAL_CATEGORY_CODES" in text
    assert "must not become DIRECT_SUPPLY" in _OBJECT_MODE_CONTRACT


def test_contextual_prior_never_direct_supply() -> None:
    proc = _proc(_mi_17723())
    sources = collect_direct_product_evidence_sources("cable_support_systems", proc)
    assert sources == []
    raw = {
        "procurement_form": "DIRECT_GOODS_PURCHASE",
        "commercial_category_hypotheses": [
            {
                "category_code": "cable_support_systems",
                "opportunity_track": "DIRECT_SUPPLY",
                "evidence_role": "CONTEXTUAL_RESEARCH_PRIOR",
                "confidence": 0.7,
            }
        ],
    }
    out = enforce_direct_supply_product_evidence(
        normalize_v3_output(raw, allowed_categories=ALLOWED, allowed_subcategories={}, has_okpd=True),
        proc,
    )
    for h in out.get("commercial_category_hypotheses") or []:
        if str(h.get("evidence_role") or "").upper() == "CONTEXTUAL_RESEARCH_PRIOR":
            assert str(h.get("opportunity_track") or "").upper() != "DIRECT_SUPPLY"


def test_direct_supply_requires_direct_product_evidence() -> None:
    proc = _proc(_mi_18434())
    raw = {
        "procurement_form": "DIRECT_GOODS_PURCHASE",
        "commercial_category_hypotheses": [
            {
                "category_code": "lighting",
                "opportunity_track": "DIRECT_SUPPLY",
                "evidence_role": "CONTEXTUAL_RESEARCH_PRIOR",
                "confidence": 0.6,
            }
        ],
    }
    out = _run(raw, proc)
    assert DIRECT_SUPPLY_REQUIRES_DIRECT_PRODUCT_EVIDENCE in (
        out.get("empty_hypothesis_reason_codes") or []
    )
    for h in out.get("commercial_category_hypotheses") or []:
        assert str(h.get("opportunity_track") or "").upper() != "DIRECT_SUPPLY" or (
            h.get("direct_product_evidence_sources")
        )


def test_network_equipment_no_cable_support_direct() -> None:
    proc = _proc(_mi_17723())
    out = _run(
        {
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "commercial_category_hypotheses": [
                {
                    "category_code": "cable_support_systems",
                    "opportunity_track": "DIRECT_SUPPLY",
                    "evidence_role": "CONTEXTUAL_RESEARCH_PRIOR",
                    "confidence": 0.7,
                }
            ],
        },
        proc,
    )
    cats = {h.get("category_code") for h in out.get("commercial_category_hypotheses") or []}
    assert "cable_support_systems" not in cats
    assert out["procurement_form"] == "DIRECT_GOODS_PURCHASE"
    assert out.get("form_coercion_applied") is False
    assert out["empty_hypothesis_status"] in ("NO_COMMERCIAL_ENTRY", "REVIEW_REQUIRED")
    assert out["empty_hypothesis_status"] == "NO_COMMERCIAL_ENTRY"


def test_high_voltage_switch_no_lighting_direct() -> None:
    proc = _proc(_mi_18434())
    out = _run(
        {
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "commercial_category_hypotheses": [
                {
                    "category_code": "lighting",
                    "opportunity_track": "DIRECT_SUPPLY",
                    "evidence_role": "CONTEXTUAL_RESEARCH_PRIOR",
                    "confidence": 0.6,
                }
            ],
        },
        proc,
    )
    cats = {h.get("category_code") for h in out.get("commercial_category_hypotheses") or []}
    assert "lighting" not in cats
    assert out["procurement_form"] == "DIRECT_GOODS_PURCHASE"
    assert out["empty_hypothesis_status"] == "NO_COMMERCIAL_ENTRY"


def test_strong_direct_goods_form_preserved() -> None:
    proc = _proc(_mi_17443())
    sdg, _ = strong_direct_goods_evidence(proc)
    sobj, _ = strong_object_procurement_evidence(proc)
    assert sdg is True
    assert sobj is False
    out = _run(
        {
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "commercial_category_hypotheses": [],
            "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
            "overall_research_action": "SKIP",
        },
        proc,
    )
    assert out["procurement_form"] == "DIRECT_GOODS_PURCHASE"
    assert out.get("form_coercion_applied") is False
    assert out.get("STRONG_DIRECT_GOODS_EVIDENCE") == "YES"
    assert out.get("routing_mode") != "OBJECT_MODE"


def test_transformer_direct_goods_17443_regression() -> None:
    proc = _proc(_mi_17443())
    out = _run(
        {
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "commercial_category_hypotheses": [
                {
                    "category_code": "composite_structures",
                    "opportunity_track": "DIRECT_SUPPLY",
                    "evidence_role": "CONTEXTUAL_RESEARCH_PRIOR",
                    "confidence": 0.4,
                }
            ],
        },
        proc,
    )
    assert out["procurement_form"] == "DIRECT_GOODS_PURCHASE"
    assert out.get("procurement_form_coerced_from") is None
    assert out.get("form_coercion_applied") is False
    assert out.get("routing_mode") != "OBJECT_MODE"
    assert out["empty_hypothesis_status"] in ("NO_COMMERCIAL_ENTRY", "REVIEW_REQUIRED")


def test_object_mode_coercion_safety_school() -> None:
    mi = {
        "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
        "procurement_id": 20228,
        "title": 'Капитальный ремонт здания МКОУ "Средняя общеобразовательная школа №6"',
        "okpd_codes": ["41.20.40.900"],
        "normalized_lifecycle": "AWARDED",
        "winner_name": 'ООО "ТРАСТ ПРОЕКТ"',
        "COMMERCIAL_PRODUCT_PRIORS": [],
        "CONTEXTUAL_RESEARCH_PRIORS": [
            {"category": "flooring", "okpd_pattern": "41.20", "prior_kind": "CONTEXTUAL_RESEARCH_PRIOR"},
        ],
    }
    proc = _proc(mi)
    sdg, _ = strong_direct_goods_evidence(proc)
    sobj, _ = strong_object_procurement_evidence(proc)
    assert sdg is False
    assert sobj is True
    out = _run(
        {
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "commercial_category_hypotheses": [
                {"category_code": "41.20.40.900", "opportunity_track": "DIRECT_SUPPLY", "confidence": 0.5}
            ],
            "empty_hypothesis_status": "REVIEW_REQUIRED",
        },
        proc,
    )
    assert out["procurement_form"] == "CONSTRUCTION_WORKS"
    assert out.get("form_coercion_applied") is True
    assert out["routing_mode"] == "OBJECT_MODE"
    assert out.get("STRONG_OBJECT_EVIDENCE") == "YES"


def test_direct_goods_nce_18215_regression() -> None:
    mi = {
        "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
        "procurement_id": 18215,
        "title": "Поставка счетчиков газа и комплектующих производства ООО «Техномер»",
        "okpd_codes": ["26.51.63.110"],
        "COMMERCIAL_PRODUCT_PRIORS": [],
        "CONTEXTUAL_RESEARCH_PRIORS": [],
    }
    out = _run(
        {
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "commercial_category_hypotheses": [],
            "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
            "overall_research_action": "SKIP",
        },
        _proc(mi),
    )
    assert out["empty_hypothesis_status"] == "NO_COMMERCIAL_ENTRY"
    assert out["overall_research_action"] == "SKIP"
    assert out.get("routing_mode") != "OBJECT_MODE"
    assert out["procurement_form"] == "DIRECT_GOODS_PURCHASE"


def test_road_object_10753_regression() -> None:
    mi = {
        "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
        "procurement_id": 10753,
        "title": "Ликвидация деформаций и разрушений покрытия на автомобильной дороге общего пользования А-146 Адыгея",
        "okpd_codes": ["42.11"],
        "COMMERCIAL_PRODUCT_PRIORS": [],
        "CONTEXTUAL_RESEARCH_PRIORS": [
            {"category": "lighting", "okpd_pattern": "42.11", "weight": 50, "prior_kind": "CONTEXTUAL_RESEARCH_PRIOR"},
            {"category": "drainage_water_management", "okpd_pattern": "42.11", "weight": 50, "prior_kind": "CONTEXTUAL_RESEARCH_PRIOR"},
        ],
    }
    proc = _proc(mi)
    obj = classify_object(proc, form="CONSTRUCTION_WORKS")
    assert obj["object_type"] == "ROAD"
    out = _run(
        {
            "procurement_form": "CONSTRUCTION_WORKS",
            "commercial_category_hypotheses": [
                {
                    "category_code": "lighting",
                    "opportunity_track": "DIRECT_SUPPLY",
                    "evidence_role": "CONTEXTUAL_RESEARCH_PRIOR",
                    "confidence": 0.8,
                }
            ],
        },
        proc,
    )
    assert out["routing_mode"] == "OBJECT_MODE"
    assert out["procurement_form"] == "CONSTRUCTION_WORKS"
    for h in out["commercial_category_hypotheses"]:
        assert h["opportunity_track"] != "DIRECT_SUPPLY"
        assert h.get("evidence_role") == "CONTEXTUAL_RESEARCH_PRIOR"


def test_independent_product_prior_keeps_direct_supply() -> None:
    mi = {
        "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
        "title": "Поставка ноутбуков",
        "okpd_codes": ["26.20.11"],
        "COMMERCIAL_PRODUCT_PRIORS": [
            {
                "category": "computers",
                "commercial_category_code": "computers",
                "okpd_pattern": "26.20",
                "prior_kind": "COMMERCIAL_PRODUCT_PRIOR",
            }
        ],
        "CONTEXTUAL_RESEARCH_PRIORS": [],
    }
    proc = _proc(mi)
    out = _run(
        {
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "commercial_category_hypotheses": [
                {
                    "category_code": "computers",
                    "opportunity_track": "DIRECT_SUPPLY",
                    "evidence_role": "CONTEXTUAL_RESEARCH_PRIOR",
                    "confidence": 0.9,
                }
            ],
        },
        proc,
    )
    hyps = out["commercial_category_hypotheses"]
    assert len(hyps) == 1
    assert hyps[0]["opportunity_track"] == "DIRECT_SUPPLY"
    assert hyps[0]["evidence_role"] != "CONTEXTUAL_RESEARCH_PRIOR"
    assert "COMMERCIAL_PRODUCT_PRIOR" in (hyps[0].get("direct_product_evidence_sources") or [])
    assert out["empty_hypothesis_status"] is None


def test_lighting_title_identity_is_direct_product_evidence() -> None:
    mi = {
        "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
        "title": "Поставка светильников",
        "okpd_codes": ["27.40.15"],
        "COMMERCIAL_PRODUCT_PRIORS": [],
        "CONTEXTUAL_RESEARCH_PRIORS": [],
    }
    proc = _proc(mi)
    sources = collect_direct_product_evidence_sources("lighting", proc)
    assert "TITLE_PRODUCT_IDENTITY" in sources
    out = _run(
        {
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "commercial_category_hypotheses": [
                {
                    "category_code": "lighting",
                    "opportunity_track": "DIRECT_SUPPLY",
                    "evidence_role": "CONTEXTUAL_RESEARCH_PRIOR",
                    "confidence": 0.8,
                }
            ],
        },
        proc,
    )
    hyps = out["commercial_category_hypotheses"]
    assert hyps[0]["opportunity_track"] == "DIRECT_SUPPLY"
    assert hyps[0]["evidence_role"] != "CONTEXTUAL_RESEARCH_PRIOR"
