"""Contract tests for 7b routing correction (track coerce + silent empty)."""
from __future__ import annotations

from src.services.commercial_routing_v3.golden_canary_validate import validate_case
from src.services.commercial_routing_v3.golden_canary_select import ReferenceExpectation
from src.services.commercial_routing_v3.normalizer import normalize_v3_output
from src.services.commercial_routing_v3.prompt import NUM_PREDICT, PROMPT_VERSION


def test_prompt_version_frozen() -> None:
    assert PROMPT_VERSION == "v3_category_centric_routing_7b_v5"
    assert NUM_PREDICT == 512


def test_construction_direct_supply_coerced_to_embedded() -> None:
    raw = {
        "procurement_form": "CONSTRUCTION_WORKS",
        "analysis_modes": ["DIRECT_PRODUCT"],
        "commercial_category_hypotheses": [
            {
                "category_code": "waterproofing",
                "subcategory_code": "SUBCATEGORY_NOT_ASSIGNED",
                "opportunity_track": "DIRECT_SUPPLY",
                "confidence": 0.7,
                "research_action": "LIGHT_RESEARCH",
                "candidate_medal": "SILVER",
                "category_value_basis": "UNKNOWN_ADDRESSABLE_VALUE",
                "reason_codes": ["title_match"],
            }
        ],
        "discovery_required": False,
    }
    out = normalize_v3_output(
        raw,
        allowed_categories={"waterproofing", "lighting", "computers"},
        allowed_subcategories={"waterproofing": set()},
        has_okpd=True,
    )
    hyp = out["commercial_category_hypotheses"][0]
    assert hyp["opportunity_track"] == "EMBEDDED_MATERIAL"
    assert "track_coerced_by_form" in hyp["reason_codes"]


def test_silent_empty_marked_invalid() -> None:
    out = normalize_v3_output(
        {
            "procurement_form": "DESIGN_ONLY",
            "analysis_modes": ["FUTURE_REQUIREMENT_DISCOVERY"],
            "commercial_category_hypotheses": [],
            "discovery_required": False,
        },
        allowed_categories={"lighting"},
        allowed_subcategories={},
        has_okpd=False,
    )
    # Contract: silent empty → REVIEW_REQUIRED + DISCOVER (never SILENT_EMPTY_INVALID)
    assert out["empty_hypothesis_status"] == "REVIEW_REQUIRED"
    assert out["overall_research_action"] == "DISCOVER_COMMERCIAL_CATEGORY"
    assert out["discovery_required"] is True
    ref = ReferenceExpectation(
        case_key="D_DESIGN_PIR",
        case_label="D",
        procurement_id=17953,
        contract_number=None,
        auction_name="изыскания",
        okpd_code="",
        okpd_name="",
        expected_category="*",
        expected_tracks=["DESIGN_REQUIREMENT", "DESIGN_INFLUENCE"],
        expected_form_hint="DESIGN_*",
    )
    v = validate_case(ref, {**out, "subcategory_explicit_ok": True}, allowed_categories={"lighting"})
    assert v["verdict"] in ("REVIEW", "PASS")
    assert "SILENT_EMPTY_HYPOTHESES" not in v["flags"]


def test_explicit_empty_insufficient_is_review() -> None:
    out = normalize_v3_output(
        {
            "procurement_form": "DESIGN_ONLY",
            "analysis_modes": ["FUTURE_REQUIREMENT_DISCOVERY"],
            "commercial_category_hypotheses": [],
            "empty_hypothesis_status": "INSUFFICIENT_EVIDENCE",
            "preferred_opportunity_track": "DESIGN_REQUIREMENT",
            "empty_hypothesis_reason_codes": ["no_sellable_category_in_title"],
            "discovery_required": True,
            "material_signals": [],
            "work_methods": [],
            "application_areas": [],
            "object_context": [],
            "brands": [],
        },
        allowed_categories={"lighting"},
        allowed_subcategories={},
        has_okpd=False,
    )
    ref = ReferenceExpectation(
        case_key="D_DESIGN_PIR",
        case_label="D",
        procurement_id=17953,
        contract_number=None,
        auction_name="изыскания",
        okpd_code="",
        okpd_name="",
        expected_category="*",
        expected_tracks=["DESIGN_REQUIREMENT", "DESIGN_INFLUENCE"],
        expected_form_hint="DESIGN_*",
    )
    v = validate_case(ref, {**out, "subcategory_explicit_ok": True}, allowed_categories={"lighting"})
    assert v["verdict"] == "REVIEW"
    assert "SILENT_EMPTY_HYPOTHESES" not in v["flags"]
