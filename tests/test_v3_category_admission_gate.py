"""Category admission gate regression control (WIP NEGATIVE-CONTROL-ADMISSION-GATE).

Invariant: NO POSITIVE CATEGORY SIGNAL -> NO CATEGORY SCORING -> medal = NONE.

The negative control is the real Novocherkassk procurement 949
("Благоустроенное жилое помещение ... для детей-сирот"), a purchase of
ready-to-move-in housing that must never receive a medal.
"""
from __future__ import annotations

from src.domain.commercial_routing_v3 import CandidateMedal
from src.services.commercial_routing_v3.category_admission import (
    ADMISSION_POLICY_VERSION,
    has_admissible_category_signal,
)
from src.services.commercial_routing_v3.candidate_scoring import (
    CandidateScoringContext,
    apply_candidate_scoring_to_hypotheses,
    score_hypothesis,
)


def _ready_housing_hypothesis(category: str = "flooring") -> dict:
    """Exact shape scored for procurement 949 (ready housing purchase)."""
    return {
        "category_code": category,
        "subcategory_code": None,
        "opportunity_track": "EMBEDDED_MATERIAL",
        "confidence": 0.0,
        "evidence_role": "CONTEXTUAL_RESEARCH_PRIOR",
        "confirmation_required": True,
        "reason_codes": ["track_coerced_by_form", "requires_document_confirmation"],
        "positive_evidence": [],
        "negative_evidence": [],
    }


def _direct_positive(category: str = "computers") -> dict:
    return {
        "category_code": category,
        "subcategory_code": None,
        "opportunity_track": "DIRECT_SUPPLY",
        "confidence": 0.95,
        "evidence_role": "COMMERCIAL_PRODUCT_PRIOR",
        "confirmation_required": False,
        "reason_codes": ["okpd_prior"],
        "positive_evidence": [],
        "negative_evidence": [],
    }


def _embedded_positive(category: str = "drainage_water_management") -> dict:
    return {
        "category_code": category,
        "subcategory_code": None,
        "opportunity_track": "EMBEDDED_MATERIAL",
        "confidence": 0.47,
        "evidence_role": "CONTEXTUAL_RESEARCH_PRIOR",
        "confirmation_required": True,
        "reason_codes": [
            "object_mode_contextual_prior",
            "requires_document_confirmation",
            "object_type:ROAD",
        ],
        "positive_evidence": [
            "object_sector:INFRASTRUCTURE",
            "object_type:ROAD",
            "work_stage:REPAIR",
        ],
        "negative_evidence": [],
    }


def test_ready_housing_has_no_positive_category_signal() -> None:
    for category in ("flooring", "waterproofing", "composite_structures"):
        admissible, source = has_admissible_category_signal(
            _ready_housing_hypothesis(category)
        )
        assert admissible is False
        assert source == "NO_POSITIVE_CATEGORY_SIGNAL"


def test_ready_housing_gets_no_scored_opportunity() -> None:
    hypotheses = [
        _ready_housing_hypothesis(category)
        for category in ("flooring", "waterproofing", "composite_structures")
    ]
    rejections: list = []
    scored = apply_candidate_scoring_to_hypotheses(
        hypotheses,
        procurement={},
        normalized={},
        admission_rejections=rejections,
    )
    assert scored == []
    assert len(rejections) == 3
    assert all(item["has_positive_category_signal"] is False for item in rejections)
    assert all(
        item["admission_policy_version"] == ADMISSION_POLICY_VERSION
        for item in rejections
    )


def test_default_components_alone_would_have_produced_a_medal() -> None:
    """Documents WHY the gate exists: defaults alone create SILVER/BRONZE.

    The stored row for procurement 949 was BRONZE (score 25.098) with no
    category evidence at all; the first acceptance had been SILVER (53).
    """
    hypothesis = _ready_housing_hypothesis()
    context = CandidateScoringContext(
        procurement_form="CONSTRUCTION_WORKS",
        normalized_lifecycle="OPEN",
        remaining_days=60,
        initial_price=3_652_000.0,
    )
    result = score_hypothesis(hypothesis, context)
    assert result.candidate_medal in (CandidateMedal.BRONZE, CandidateMedal.SILVER)
    # Admission rejects it first, so no opportunity and no medal are produced.
    assert (
        apply_candidate_scoring_to_hypotheses(
            [hypothesis], procurement={}, normalized={}
        )
        == []
    )


def test_default_components_cannot_create_opportunity() -> None:
    defaults = [
        {
            "category_code": category,
            "opportunity_track": "UNKNOWN",
            "confidence": 0.0,
            "reason_codes": [],
            "positive_evidence": [],
        }
        for category in ("waterproofing", "flooring", "lighting")
    ]
    assert (
        apply_candidate_scoring_to_hypotheses(
            defaults, procurement={}, normalized={}
        )
        == []
    )


def test_direct_goods_without_category_evidence_is_rejected() -> None:
    no_evidence = {
        "category_code": "computers",
        "opportunity_track": "DIRECT_SUPPLY",
        "confidence": 0.0,
        "reason_codes": [],
        "positive_evidence": [],
    }
    admissible, _ = has_admissible_category_signal(no_evidence)
    assert admissible is False


def test_direct_positive_controls_preserved() -> None:
    hypotheses = [
        _direct_positive(category)
        for category in (
            "computers",
            "cable_support_systems",
            "lighting",
            "flooring",
            "waterproofing",
        )
    ]
    scored = apply_candidate_scoring_to_hypotheses(
        hypotheses, procurement={}, normalized={}
    )
    assert len(scored) == 5
    assert all(row["category_admission_signal"] for row in scored)


def test_embedded_positive_controls_preserved() -> None:
    hypotheses = [
        _embedded_positive(category)
        for category in (
            "drainage_water_management",
            "curbstone",
            "composite_structures",
            "flooring",
            "waterproofing",
        )
    ]
    scored = apply_candidate_scoring_to_hypotheses(
        hypotheses,
        procurement={"v3_model_input": {"normalized_lifecycle": "OPEN"}},
        normalized={"procurement_form": "CONSTRUCTION_WORKS"},
    )
    assert len(scored) == 5
    assert all(row["category_admission_signal"] for row in scored)
