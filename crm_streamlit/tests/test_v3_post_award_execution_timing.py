"""CRM-V3-AWARDED-EXECUTION-WINDOW-COMMERCIAL-TIMING-1 tests."""
from __future__ import annotations

from datetime import date

import pytest

from src.domain.commercial_routing_v3 import CandidateMedal, OpportunityTrack
from src.services.commercial_routing_v3.candidate_scoring import (
    CANDIDATE_SCORING_VERSION,
    CandidateScoringContext,
    check_medal_monotonicity,
    score_hypothesis,
)
from src.services.commercial_routing_v3.post_award_execution_timing import (
    ExecutionPhase,
    POST_AWARD_TIMING_VERSION,
    classify_execution_phase,
    clock_from_model_input,
    compute_execution_clock,
    compute_post_award_commercial_timing_value,
)


def _school_hypothesis() -> dict:
    return {
        "category_code": "flooring",
        "opportunity_track": OpportunityTrack.EMBEDDED_MATERIAL.value,
        "evidence_role": "CONTEXTUAL_RESEARCH_PRIOR",
        "confirmation_required": True,
        "confidence": 0.5,
    }


def _school_ctx(**overrides) -> CandidateScoringContext:
    mi = {
        "normalized_lifecycle": "AWARDED",
        "delivery_start_at": "2025-08-01",
        "delivery_end_at": "2026-08-01",
        "execution_remaining_days": 17,
        "initial_price": 99_000_000.0,
        "final_contract_price": 99_000_000.0,
    }
    mi.update(overrides.pop("mi_overrides", {}))
    clock = clock_from_model_input(mi)
    base = {
        "procurement_form": "CONSTRUCTION_WORKS",
        "normalized_lifecycle": "AWARDED",
        "object_classification": {
            "object_type": "SCHOOL",
            "object_sector": "SOCIAL_INFRASTRUCTURE",
            "work_stage": "CAPITAL_REPAIR",
        },
        "execution_remaining_days": 17.0,
        "initial_price": 99_000_000.0,
        "final_contract_price": 99_000_000.0,
        "execution_clock": clock,
    }
    base.update(overrides)
    return CandidateScoringContext(**base)


def test_execution_clock_365_17_closing() -> None:
    clock = compute_execution_clock(
        delivery_start_at="2025-08-01",
        delivery_end_at="2026-08-01",
        as_of=date(2026, 7, 15),
    )
    assert clock.execution_total_days == pytest.approx(365.0, abs=1.0)
    assert clock.execution_remaining_days == pytest.approx(17.0, abs=1.0)
    assert clock.execution_remaining_ratio == pytest.approx(17 / 365, rel=0.05)
    assert clock.execution_phase == ExecutionPhase.CLOSING
    assert clock.post_award_commercial_timing_value is not None
    assert clock.post_award_commercial_timing_value <= 20.0


@pytest.mark.parametrize(
    "total, remaining, expected_phase",
    [
        (365, 17, ExecutionPhase.CLOSING),
        (365, 127, ExecutionPhase.MID_EXECUTION),
        (365, 300, ExecutionPhase.EARLY_EXECUTION),
        (120, 90, ExecutionPhase.EARLY_EXECUTION),
        (120, 15, ExecutionPhase.CLOSING),
    ],
)
def test_execution_phase_matrix(total: int, remaining: int, expected_phase: ExecutionPhase) -> None:
    ratio = remaining / total
    phase = classify_execution_phase(
        total_days=float(total),
        remaining_days=float(remaining),
        remaining_ratio=ratio,
    )
    assert phase == expected_phase


def test_post_award_timing_relative_and_absolute_ordering() -> None:
    a = compute_post_award_commercial_timing_value(
        remaining_days=17.0,
        remaining_ratio=17 / 365,
        phase=ExecutionPhase.CLOSING,
    )
    b = compute_post_award_commercial_timing_value(
        remaining_days=127.0,
        remaining_ratio=127 / 365,
        phase=ExecutionPhase.MID_EXECUTION,
    )
    c = compute_post_award_commercial_timing_value(
        remaining_days=300.0,
        remaining_ratio=300 / 365,
        phase=ExecutionPhase.EARLY_EXECUTION,
    )
    assert a is not None and b is not None and c is not None
    assert a < b < c
    assert c >= 70.0


def test_20228_very_late_not_silver_from_scale_only() -> None:
    ctx = _school_ctx()
    r = score_hypothesis(_school_hypothesis(), ctx)
    assert r.execution_audit is not None
    assert r.execution_audit["execution_phase"] == ExecutionPhase.CLOSING.value
    assert r.hard_cap == CandidateMedal.WOOD.name
    assert r.candidate_medal == CandidateMedal.WOOD
    assert r.final_score < 50.0
    assert r.score_components["commercial_timing_score"] <= 20.0


def test_awarded_execution_clock_test_pass() -> None:
    clock = compute_execution_clock(
        delivery_start_at="2025-01-01",
        delivery_end_at="2026-01-01",
        as_of=date(2025, 6, 1),
    )
    assert clock.execution_total_days is not None
    assert clock.execution_elapsed_days is not None
    assert clock.execution_remaining_days is not None
    assert clock.execution_elapsed_ratio is not None
    assert clock.execution_remaining_ratio is not None
    assert clock.execution_timing_status == "USED"
    assert clock.post_award_timing_version == POST_AWARD_TIMING_VERSION


def test_suspect_execution_dates_suppressed() -> None:
    mi_sus = {
        "normalized_lifecycle": "AWARDED",
        "delivery_start_at": "2026-01-01",
        "delivery_end_at": "2026-01-01",
        "execution_remaining_days": 120,
        "source_table": "reestr_contract_44_fz_awarded",
    }
    clock_sus = clock_from_model_input(mi_sus, source_data_quality="SUSPECT")
    assert clock_sus.execution_timing_status == "SUPPRESSED_SOURCE_SUSPECT"
    as_of = date(2025, 9, 1)
    clock_ok = compute_execution_clock(
        delivery_start_at="2025-01-01",
        delivery_end_at="2026-01-01",
        as_of=as_of,
    )
    ctx_ok = CandidateScoringContext(
        procurement_form="CONSTRUCTION_WORKS",
        normalized_lifecycle="AWARDED",
        object_classification={"object_type": "SCHOOL", "work_stage": "CAPITAL_REPAIR"},
        initial_price=80_000_000.0,
        execution_clock=clock_ok,
        source_data_quality="OK",
    )
    ctx_sus = CandidateScoringContext(
        procurement_form="CONSTRUCTION_WORKS",
        normalized_lifecycle="AWARDED",
        object_classification={"object_type": "SCHOOL", "work_stage": "CAPITAL_REPAIR"},
        initial_price=80_000_000.0,
        execution_clock=clock_sus,
        source_data_quality="SUSPECT",
    )
    r_ok = score_hypothesis(_school_hypothesis(), ctx_ok)
    r_sus = score_hypothesis(_school_hypothesis(), ctx_sus)
    assert r_sus.execution_timing_status == "SUPPRESSED_SOURCE_SUSPECT"
    assert r_sus.score_components["commercial_timing_score"] <= r_ok.score_components["commercial_timing_score"]


def test_scoring_version_bumped() -> None:
    assert CANDIDATE_SCORING_VERSION == "v2_post_award_execution_20260814"


def test_medal_monotonicity_awarded_mixed_phases() -> None:
    early = score_hypothesis(
        _school_hypothesis(),
        _school_ctx(
            mi_overrides={
                "delivery_start_at": "2025-01-01",
                "delivery_end_at": "2026-01-01",
                "execution_remaining_days": 300,
            },
            execution_clock=compute_execution_clock(
                delivery_start_at="2025-01-01",
                delivery_end_at="2026-01-01",
                as_of=date(2025, 3, 7),
            ),
        ),
    )
    late = score_hypothesis(_school_hypothesis(), _school_ctx())
    rows = [
        {"category_code": "flooring", "final_score": early.final_score, "candidate_medal": early.candidate_medal.value},
        {"category_code": "waterproofing", "final_score": late.final_score, "candidate_medal": late.candidate_medal.value, "hard_cap": late.hard_cap},
    ]
    assert check_medal_monotonicity(rows) == []
