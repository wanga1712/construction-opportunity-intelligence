"""CRM-V3-CANDIDATE-SCORING-AND-CATEGORY-CONTRACT-CALIBRATION-1 tests."""
from __future__ import annotations

from datetime import date

from src.domain.commercial_routing_v3 import CandidateMedal, OpportunityTrack
from src.domain.commercial_taxonomy import COMMERCIAL_KEEP_CODES
from src.services.commercial_routing_v3.candidate_scoring import (
    CANDIDATE_SCORING_VERSION,
    CandidateScoringContext,
    apply_candidate_scoring_to_hypotheses,
    check_medal_monotonicity,
    looks_like_okpd_category_code,
    medal_from_score,
    score_hypothesis,
)
from src.services.commercial_routing_v3.post_award_execution_timing import compute_execution_clock
from src.services.commercial_routing_v3.category_aliases import (
    CANONICAL_CATEGORY_ALIASES,
    resolve_explicit_category_alias,
)
from src.services.commercial_routing_v3.model_input import model_input_as_prompt_procurement
from src.services.commercial_routing_v3.normalizer import normalize_v3_output
from src.services.commercial_routing_v3.object_mode_routing import enrich_object_mode_routing
from src.services.commercial_routing_v3.prompt import PROMPT_VERSION, allowed_category_codes_block

ALLOWED = set(COMMERCIAL_KEEP_CODES)


def test_prompt_version_v5() -> None:
    assert PROMPT_VERSION == "v3_category_centric_routing_7b_v5"


def test_candidate_score_single_authority() -> None:
    from src.services.commercial_routing_v3.post_award_execution_timing import compute_execution_clock
    from datetime import date

    clock = compute_execution_clock(
        delivery_start_at="2025-08-01",
        delivery_end_at="2026-08-01",
        as_of=date(2026, 7, 15),
    )
    hyp = {
        "category_code": "flooring",
        "opportunity_track": OpportunityTrack.EMBEDDED_MATERIAL.value,
        "evidence_role": "CONTEXTUAL_RESEARCH_PRIOR",
        "confirmation_required": True,
        "confidence": 0.5,
    }
    ctx = CandidateScoringContext(
        procurement_form="CONSTRUCTION_WORKS",
        normalized_lifecycle="AWARDED",
        object_classification={
            "object_type": "SCHOOL",
            "object_sector": "SOCIAL_INFRASTRUCTURE",
            "work_stage": "CAPITAL_REPAIR",
        },
        execution_remaining_days=17.0,
        initial_price=99_000_000.0,
        final_contract_price=99_000_000.0,
        execution_clock=clock,
    )
    r = score_hypothesis(hyp, ctx)
    assert r.candidate_scoring_version == CANDIDATE_SCORING_VERSION
    medal, _, _ = medal_from_score(r.final_score, hard_cap=CandidateMedal.WOOD if r.hard_cap else None)
    assert medal == r.candidate_medal
    assert r.candidate_medal == CandidateMedal.WOOD


def test_medal_monotonicity() -> None:
    hyps = [
        {
            "category_code": "flooring",
            "opportunity_track": "EMBEDDED_MATERIAL",
            "evidence_role": "CONTEXTUAL_RESEARCH_PRIOR",
            "confirmation_required": True,
            "confidence": 0.5,
        },
        {
            "category_code": "waterproofing",
            "opportunity_track": "EMBEDDED_MATERIAL",
            "evidence_role": "CONTEXTUAL_RESEARCH_PRIOR",
            "confirmation_required": True,
            "confidence": 0.45,
        },
    ]
    scored = apply_candidate_scoring_to_hypotheses(
        hyps,
        procurement={"v3_model_input": {"normalized_lifecycle": "AWARDED", "execution_remaining_days": 17}},
        normalized={"procurement_form": "CONSTRUCTION_WORKS", "object_classification": {"object_type": "SCHOOL"}},
    )
    assert check_medal_monotonicity(scored) == []


def test_no_hidden_downgrade_without_hard_cap() -> None:
    for score, expected in (
        (76.0, CandidateMedal.GOLD),
        (55.0, CandidateMedal.SILVER),
        (30.0, CandidateMedal.BRONZE),
    ):
        medal, cap, reason = medal_from_score(score)
        assert medal == expected
        assert cap is None


def test_candidate_confirmation_independence() -> None:
    hyp = {
        "category_code": "flooring",
        "opportunity_track": "EMBEDDED_MATERIAL",
        "evidence_role": "CONTEXTUAL_RESEARCH_PRIOR",
        "confirmation_required": True,
        "confidence": 0.55,
    }
    ctx = CandidateScoringContext(
        procurement_form="CONSTRUCTION_WORKS",
        normalized_lifecycle="AWARDED",
        object_classification={"object_type": "SCHOOL", "work_stage": "CAPITAL_REPAIR"},
        execution_remaining_days=120.0,
        initial_price=80_000_000.0,
        execution_clock=compute_execution_clock(
            delivery_start_at="2025-01-01",
            delivery_end_at="2026-01-01",
            as_of=date(2025, 9, 3),
        ),
    )
    r = score_hypothesis(hyp, ctx)
    assert r.candidate_medal != CandidateMedal.WOOD
    assert r.final_score >= 25.0


def test_suspect_timing_suppressed() -> None:
    hyp = {
        "category_code": "drainage_water_management",
        "opportunity_track": "EMBEDDED_MATERIAL",
        "evidence_role": "CONTEXTUAL_RESEARCH_PRIOR",
        "confirmation_required": True,
        "confidence": 0.4,
    }
    ctx_ok = CandidateScoringContext(
        procurement_form="CONSTRUCTION_WORKS",
        source_data_quality="OK",
        commercial_timing_value=90.0,
        object_classification={"object_type": "ROAD"},
        remaining_days=20.0,
    )
    ctx_sus = CandidateScoringContext(
        procurement_form="CONSTRUCTION_WORKS",
        source_data_quality="SUSPECT",
        commercial_timing_value=90.0,
        object_classification={"object_type": "ROAD"},
        remaining_days=20.0,
    )
    r_ok = score_hypothesis(hyp, ctx_ok)
    r_sus = score_hypothesis(hyp, ctx_sus)
    assert r_sus.timing_component_status == "SUPPRESSED_SOURCE_SUSPECT"
    assert r_sus.score_components["commercial_timing_score"] < r_ok.score_components["commercial_timing_score"]


def test_suspect_data_not_automatic_wood() -> None:
    hyp = {
        "category_code": "flooring",
        "opportunity_track": "EMBEDDED_MATERIAL",
        "evidence_role": "CONTEXTUAL_RESEARCH_PRIOR",
        "confirmation_required": True,
        "confidence": 0.5,
    }
    ctx = CandidateScoringContext(
        procurement_form="CONSTRUCTION_WORKS",
        source_data_quality="SUSPECT",
        object_classification={"object_type": "SCHOOL"},
        execution_remaining_days=20.0,
        initial_price=50_000_000.0,
    )
    r = score_hypothesis(hyp, ctx)
    assert r.candidate_medal != CandidateMedal.WOOD


def test_okpd_not_category_code() -> None:
    assert looks_like_okpd_category_code("41.20.40.900")
    out = normalize_v3_output(
        {
            "procurement_form": "CONSTRUCTION_WORKS",
            "commercial_category_hypotheses": [{"category_code": "42.11", "opportunity_track": "EMBEDDED_MATERIAL"}],
        },
        allowed_categories=ALLOWED,
        allowed_subcategories={},
        has_okpd=True,
    )
    assert "42.11" in out["rejected_category_codes"]
    assert not out["commercial_category_hypotheses"]


def test_allowed_registry_category_contract() -> None:
    block = allowed_category_codes_block(
        [{"category_code": c, "category_name": c, "lifecycle_state": "ACTIVE"} for c in sorted(ALLOWED)]
    )
    assert "ALLOWED_COMMERCIAL_CATEGORY_CODES" in block
    assert "lighting" in block


def test_category_alias_explicit_only() -> None:
    assert resolve_explicit_category_alias("COMPUTERS", allowed_categories=ALLOWED) == "computers"
    assert resolve_explicit_category_alias("totally_unknown_xyz", allowed_categories=ALLOWED) is None
    assert "COMPUTERS" in CANONICAL_CATEGORY_ALIASES


def test_computers_alias_normalizer() -> None:
    out = normalize_v3_output(
        {
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "commercial_category_hypotheses": [
                {"category_code": "COMPUTERS", "opportunity_track": "DIRECT_SUPPLY", "confidence": 0.7}
            ],
        },
        allowed_categories=ALLOWED,
        allowed_subcategories={},
        has_okpd=True,
    )
    assert out["commercial_category_hypotheses"][0]["category_code"] == "computers"


def test_direct_goods_nce_regression() -> None:
    mi = {
        "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
        "procurement_id": 18215,
        "title": "Поставка счетчиков газа",
        "okpd_codes": ["26.51.63.110"],
        "CONTEXTUAL_RESEARCH_PRIORS": [],
    }
    proc = model_input_as_prompt_procurement(mi)
    proc["v3_model_input"] = mi
    out = enrich_object_mode_routing(
        normalize_v3_output(
            {
                "procurement_form": "DIRECT_GOODS_PURCHASE",
                "commercial_category_hypotheses": [],
                "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
                "overall_research_action": "SKIP",
            },
            allowed_categories=ALLOWED,
            allowed_subcategories={},
            has_okpd=True,
        ),
        proc,
        allowed_categories=ALLOWED,
    )
    assert out["empty_hypothesis_status"] == "NO_COMMERCIAL_ENTRY"


def test_object_mode_road_regression() -> None:
    mi = {
        "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
        "title": "Ликвидация деформаций покрытия автомобильной дороги",
        "okpd_codes": ["42.11"],
        "CONTEXTUAL_RESEARCH_PRIORS": [{"category": "drainage_water_management", "weight": 50}],
    }
    proc = model_input_as_prompt_procurement(mi)
    proc["v3_model_input"] = mi
    out = enrich_object_mode_routing(
        normalize_v3_output(
            {"procurement_form": "CONSTRUCTION_WORKS", "commercial_category_hypotheses": [], "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY"},
            allowed_categories=ALLOWED,
            allowed_subcategories={},
            has_okpd=True,
        ),
        proc,
        allowed_categories=ALLOWED,
    )
    assert out["routing_mode"] == "OBJECT_MODE"
    assert len(out["commercial_category_hypotheses"]) >= 1


def test_awarded_school_regression() -> None:
    mi = {
        "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
        "title": "Капитальный ремонт здания школы",
        "okpd_codes": ["41.20.40.900"],
        "normalized_lifecycle": "AWARDED",
        "winner_name": 'ООО "ТРАСТ ПРОЕКТ"',
        "CONTEXTUAL_RESEARCH_PRIORS": [{"category": "flooring", "weight": 50}],
    }
    proc = model_input_as_prompt_procurement(mi)
    proc["v3_model_input"] = mi
    out = enrich_object_mode_routing(
        normalize_v3_output(
            {"procurement_form": "DIRECT_GOODS_PURCHASE", "commercial_category_hypotheses": [], "empty_hypothesis_status": "REVIEW_REQUIRED"},
            allowed_categories=ALLOWED,
            allowed_subcategories={},
            has_okpd=True,
        ),
        proc,
        allowed_categories=ALLOWED,
    )
    assert out["routing_mode"] == "OBJECT_MODE"
    assert out.get("post_award_commercial_target") == "WINNER_CONTRACTOR"
