"""PROJECT_LIFECYCLE_V1 targeted tests: DIRECT vs PROJECT freshness separation.

Covers WIP PROJECT_LIFECYCLE_V1 acceptance:
1. DIRECT and PROJECT do not share one freshness model.
2. Ended tender does not kill a live construction project.
3. Active project with a confirmed category signal can reach the document queue.
4. Ready-housing purchase (pid949 shape) never becomes a project opportunity.
"""
from __future__ import annotations

from datetime import date, timedelta

from src.services.commercial_routing_v3.candidate_scoring import (
    CandidateScoringContext,
    score_hypothesis,
)
from src.services.commercial_routing_v3.category_admission import (
    has_admissible_category_signal,
)
from src.services.commercial_routing_v3.project_lifecycle import (
    PROJECT_END_SOURCE,
    PROJECT_TRACKS,
    compute_project_clock,
    evaluate_project_admission,
    is_project_track,
    project_dates_from_source,
    project_ui_semantics,
)

TODAY = date(2026, 10, 9)


def _proc(*, start="2025-01-01", end="2027-02-10"):
    return {"delivery_start_date": start, "delivery_end_date": end}


def test_project_track_and_end_source_are_not_submission():
    assert PROJECT_TRACKS == frozenset({"EMBEDDED_MATERIAL"})
    assert is_project_track("EMBEDDED_MATERIAL")
    assert not is_project_track("DIRECT_SUPPLY")
    assert "submission_deadline_at" in PROJECT_END_SOURCE
    # end_date (submission window for OPEN) must never be a project-end fallback
    start, end = project_dates_from_source(
        {"start_date": "2026-01-01", "end_date": "2026-06-15"}
    )
    assert (start, end) == (None, None)


def test_active_project_with_signal_is_admitted_even_when_awarded():
    clock = compute_project_clock(_proc(), as_of=TODAY)
    assert clock.project_active is True
    assert clock.project_end_at == "2027-02-10"
    decision = evaluate_project_admission(
        track="EMBEDDED_MATERIAL", has_positive_category_signal=True, project_clock=clock
    )
    assert decision["document_admission"] is True
    assert decision["reason"] == "PROJECT_ACTIVE"


def test_active_project_without_signal_is_not_admitted():
    clock = compute_project_clock(_proc(), as_of=TODAY)
    decision = evaluate_project_admission(
        track="EMBEDDED_MATERIAL", has_positive_category_signal=False, project_clock=clock
    )
    assert decision["project_active"] is True
    assert decision["document_admission"] is False
    assert decision["reason"] == "NO_POSITIVE_CATEGORY_SIGNAL"


def test_completed_or_unknown_project_is_not_admitted():
    past = compute_project_clock({"delivery_end_date": "2025-01-01"}, as_of=TODAY)
    assert past.project_active is False
    assert (
        evaluate_project_admission(
            track="EMBEDDED_MATERIAL", has_positive_category_signal=True, project_clock=past
        )["document_admission"]
        is False
    )

    unknown = compute_project_clock({}, as_of=TODAY)
    assert unknown.project_end_at is None
    assert (
        evaluate_project_admission(
            track="EMBEDDED_MATERIAL",
            has_positive_category_signal=True,
            project_clock=unknown,
        )["reason"]
        == "PROJECT_END_UNKNOWN"
    )


def test_direct_track_is_out_of_project_scope():
    clock = compute_project_clock(_proc(), as_of=TODAY)
    assert (
        evaluate_project_admission(
            track="DIRECT_SUPPLY", has_positive_category_signal=True, project_clock=clock
        )["document_admission"]
        is False
    )
    assert (
        project_ui_semantics(track="DIRECT_SUPPLY", lifecycle="OPEN", project_clock=clock)
        is None
    )


def test_ui_semantics_never_show_submission_as_project_life():
    clock = compute_project_clock(_proc(), as_of=TODAY)
    sem = project_ui_semantics(
        track="EMBEDDED_MATERIAL", lifecycle="AWARDED", project_clock=clock
    )
    assert sem["tender_status"] == "завершены"
    assert sem["project_status"] == "Активен"
    assert sem["project_end"] == "2027-02-10"


def _ctx(**kw):
    base = dict(
        procurement_form="CONSTRUCTION_WORKS",
        normalized_lifecycle="AWARDED",
        object_classification={"object_type": "SCHOOL"},
        initial_price=50_000_000.0,
        category_confidence=0.6,
    )
    base.update(kw)
    return CandidateScoringContext(**base)


def test_project_timing_uses_project_end_not_submission_deadline():
    hyp = {
        "category_code": "flooring",
        "opportunity_track": "EMBEDDED_MATERIAL",
        "evidence_role": "COMMERCIAL_PRODUCT_PRIOR",
        "confidence": 0.6,
    }
    # Submission long expired, project still has ~16 months of runway.
    ctx = _ctx(
        normalized_lifecycle="WAITING_SOURCE_OUTCOME",
        remaining_days=-120.0,
        project_active=True,
        project_timing_value=72.0,
        project_remaining_days=480.0,
    )
    res = score_hypothesis(hyp, ctx)
    assert res.score_components["commercial_timing_score"] == 72.0
    assert "procedure_near_expiry" not in res.downgrade_reasons

    # Same expired submission without project context decays hard (old behaviour).
    decayed = score_hypothesis(
        hyp, _ctx(normalized_lifecycle="WAITING_SOURCE_OUTCOME", remaining_days=-120.0)
    )
    assert (
        decayed.score_components["commercial_timing_score"]
        < res.score_components["commercial_timing_score"]
    )


def test_direct_supply_keeps_submission_freshness_model():
    hyp = {
        "category_code": "computers",
        "opportunity_track": "DIRECT_SUPPLY",
        "evidence_role": "COMMERCIAL_PRODUCT_PRIOR",
        "confidence": 0.8,
    }
    res = score_hypothesis(
        hyp,
        _ctx(
            procurement_form="DIRECT_GOODS_PURCHASE",
            normalized_lifecycle="OPEN",
            remaining_days=2.0,
        ),
    )
    assert res.score_components["commercial_timing_score"] == 20.0
    assert "procedure_near_expiry" not in res.downgrade_reasons


def test_ready_property_purchase_is_not_a_project_opportunity():
    """pid949 negative control: no category signal -> not admitted."""
    hyp = {
        "category_code": "flooring",
        "opportunity_track": "EMBEDDED_MATERIAL",
        "category_confidence": 0.0,
        "confidence": 0.0,
        "positive_evidence": [],
        "reason_codes": ["track_coerced_by_form", "requires_document_confirmation"],
    }
    ok, source = has_admissible_category_signal(hyp)
    assert ok is False
    assert source == "NO_POSITIVE_CATEGORY_SIGNAL"
    clock = compute_project_clock(
        {"delivery_end_date": str(date.today() + timedelta(days=200))}
    )
    decision = evaluate_project_admission(
        track="EMBEDDED_MATERIAL", has_positive_category_signal=ok, project_clock=clock
    )
    assert decision["document_admission"] is False
