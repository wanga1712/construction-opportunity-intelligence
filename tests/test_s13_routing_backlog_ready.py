"""Targeted routing backlog/ready behavior ported from S13."""
from __future__ import annotations

from src.services.commercial_routing_v3.routing_backlog import (
    classify_eligible_backlog,
)
from src.services.commercial_routing_v3.routing_ready import (
    allocate_production_routing_batch,
)


def _candidate(candidate_id: int, lane: str, **extra):
    return {
        "id": candidate_id,
        "procurement_id": candidate_id,
        "routing_lane": lane,
        "eligibility_reason": "PENDING",
        "ai_assessment_status": "UNASSESSED",
        **extra,
    }


def test_backlog_separates_live_and_full_routing_totals() -> None:
    out = classify_eligible_backlog(
        [
            _candidate(1, "ACTIVE_OPEN"),
            _candidate(2, "AWARDED_ADMITTED"),
            _candidate(3, "REVIEW_DISCOVERY"),
            _candidate(4, "REVIEW_DISCOVERY"),
        ]
    )
    assert out["ACTIVE_BACKLOG"] == 1
    assert out["AWARDED_BACKLOG"] == 1
    assert out["REVIEW_DISCOVERY"] == 2
    assert out["LIVE_ROUTING_ELIGIBLE_BACKLOG"] == 2
    assert out["TOTAL_ROUTING_ELIGIBLE_BACKLOG"] == 4


def test_backlog_total_does_not_double_count_lane_members() -> None:
    candidates = [
        _candidate(1, "ACTIVE_OPEN"),
        _candidate(2, "AWARDED_ADMITTED"),
        _candidate(3, "REVIEW_DISCOVERY"),
    ]
    out = classify_eligible_backlog(candidates)
    assert out["TOTAL_ROUTING_ELIGIBLE_BACKLOG"] == len(candidates)
    assert out["ACTIVE_BACKLOG"] + out["AWARDED_BACKLOG"] + out["OTHER_SELECTABLE_LANES"] == len(
        candidates
    )


def test_ready_fills_remaining_capacity_from_review_discovery() -> None:
    candidates = [
        _candidate(10, "ACTIVE_OPEN", end_date="2026-12-01"),
        _candidate(11, "AWARDED_ADMITTED", end_date="2026-12-02"),
        _candidate(12, "REVIEW_DISCOVERY", end_date="2026-12-03"),
        _candidate(13, "REVIEW_DISCOVERY", end_date="2026-12-04"),
    ]
    selected = allocate_production_routing_batch(candidates, total=4)
    assert [row["id"] for row in selected[:2]] == [10, 11]
    assert {row["id"] for row in selected[2:]} == {12, 13}
    assert len(selected) == 4


def test_ready_never_exceeds_capacity_or_duplicates() -> None:
    candidates = [
        _candidate(1, "ACTIVE_OPEN"),
        _candidate(2, "AWARDED_ADMITTED"),
        _candidate(3, "REVIEW_DISCOVERY"),
        _candidate(4, "REVIEW_DISCOVERY"),
        _candidate(5, "REVIEW_DISCOVERY"),
    ]
    selected = allocate_production_routing_batch(candidates, total=3)
    assert len(selected) == 3
    assert len({row["id"] for row in selected}) == len(selected)
    assert len(selected) <= 3
