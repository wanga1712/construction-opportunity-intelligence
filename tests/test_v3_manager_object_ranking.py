"""CRM-V3-AWARDED-CLOSING-ELIGIBILITY-AND-MANAGER-RANKING-1 tests."""
from __future__ import annotations

from src.domain.commercial_routing_v3 import CandidateMedal
from src.services.commercial_routing_v3.manager_object_ranking import (
    ManagerActionability,
    WorkbenchCommercialState,
    build_manager_object,
    commercial_window_closed_reason,
    count_actionable_bronze_below_closing_wood,
    manager_priority_score,
    rank_manager_objects,
    ranking_respects_final_medal,
    resolve_workbench_state,
)


def _item(
    pid: int,
    *,
    lifecycle: str = "OPEN",
    medal: str = "BRONZE",
    final_score: float = 36.4,
    raw_score: float = 40.0,
    phase: str | None = None,
    hard_cap: str | None = None,
    hard_cap_reason: str | None = None,
    routing_mode: str = "OBJECT_MODE",
    empty: str | None = None,
) -> dict:
    hyp = {
        "category": "flooring",
        "candidate_medal": medal,
        "candidate_score": final_score,
        "final_score": final_score,
        "base_score": raw_score,
        "hard_cap": hard_cap,
        "hard_cap_reason": hard_cap_reason,
    }
    if phase:
        hyp["execution_clock"] = {"execution_phase": phase, "post_award_commercial_timing_value": 7.5}
    return {
        "procurement_id": pid,
        "title": f"proc {pid}",
        "lifecycle": lifecycle,
        "routing_mode": routing_mode,
        "empty_hypothesis_status": empty,
        "hypotheses": [hyp] if empty != "NO_COMMERCIAL_ENTRY" else [],
        "object_type": "SCHOOL" if lifecycle == "AWARDED" else "ROAD",
        "work_stage": "CAPITAL_REPAIR" if lifecycle == "AWARDED" else "REPAIR",
    }


def test_medal_priority_bronze_beats_wood_despite_lower_raw_score() -> None:
    wood = build_manager_object(
        _item(20228, lifecycle="AWARDED", medal="WOOD", final_score=48.9, raw_score=48.9, phase="CLOSING", hard_cap="WOOD", hard_cap_reason="post_award_closing_execution_phase")
    )
    bronze = build_manager_object(_item(7802, medal="BRONZE", final_score=36.4))
    actionable, closed = rank_manager_objects([wood, bronze])
    assert wood["workbench_status"] == WorkbenchCommercialState.COMMERCIAL_WINDOW_CLOSED.value
    assert wood["PREQUALIFIED_AWARDED"] is False
    assert bronze in actionable
    assert wood in closed
    assert actionable[0]["procurement_id"] == 7802
    assert ranking_respects_final_medal([wood, bronze])


def test_silver_beats_bronze_beats_wood_actionable() -> None:
    objs = [
        build_manager_object(_item(1, medal="WOOD", final_score=90.0)),
        build_manager_object(_item(2, medal="BRONZE", final_score=30.0)),
        build_manager_object(_item(3, medal="SILVER", final_score=55.0)),
    ]
    actionable, _ = rank_manager_objects(objs)
    ranks = [o["procurement_id"] for o in actionable]
    assert ranks == [3, 2, 1]


def test_closing_awarded_not_prequalified() -> None:
    obj = build_manager_object(
        _item(
            20228,
            lifecycle="AWARDED",
            medal="WOOD",
            final_score=48.9,
            phase="CLOSING",
            hard_cap="WOOD",
            hard_cap_reason="post_award_closing_execution_phase",
        )
    )
    assert obj["PREQUALIFIED_AWARDED"] is False
    assert obj["manager_actionability"] == ManagerActionability.NOT_ACTIONABLE.value
    assert obj["commercial_window_closed"] is True
    assert obj["commercial_eligibility_reason"] == "post_award_execution_phase_closing"


def test_awarded_with_runway_stays_prequalified() -> None:
    obj = build_manager_object(
        _item(
            19572,
            lifecycle="AWARDED",
            medal="SILVER",
            final_score=64.8,
            phase="MID_EXECUTION",
        )
    )
    assert obj["PREQUALIFIED_AWARDED"] is True
    assert obj["workbench_status"] == WorkbenchCommercialState.PREQUALIFIED_AWARDED.value


def test_nce_unchanged() -> None:
    obj = build_manager_object(_item(18215, empty="NO_COMMERCIAL_ENTRY", routing_mode="DIRECT_OR_OTHER"))
    assert obj["workbench_status"] == WorkbenchCommercialState.NO_COMMERCIAL_ENTRY.value
    assert commercial_window_closed_reason(
        lifecycle="OPEN",
        routing_mode="DIRECT_OR_OTHER",
        empty_hypothesis_status="NO_COMMERCIAL_ENTRY",
        execution_phase=None,
        hard_cap=None,
        hard_cap_reason=None,
        has_candidates=False,
    ) is None


def test_manager_priority_score_ordering() -> None:
    assert manager_priority_score(CandidateMedal.BRONZE, 36.4) > manager_priority_score(
        CandidateMedal.WOOD, 48.9
    )


def test_closed_not_in_primary_prequalified_ranking() -> None:
    objs = [
        build_manager_object(
            _item(20228, lifecycle="AWARDED", medal="WOOD", final_score=48.9, phase="CLOSING", hard_cap="WOOD", hard_cap_reason="post_award_closing_execution_phase")
        ),
        build_manager_object(_item(19419, lifecycle="AWARDED", medal="WOOD", final_score=47.7, phase="CLOSING", hard_cap="WOOD", hard_cap_reason="post_award_closing_execution_phase"),
        ),
        build_manager_object(_item(7802, medal="BRONZE", final_score=36.4)),
    ]
    actionable, closed = rank_manager_objects(objs)
    assert count_actionable_bronze_below_closing_wood(objs) == 0
    assert all(o["procurement_id"] in (20228, 19419) for o in closed)
    assert actionable[0]["procurement_id"] == 7802


def test_resolve_workbench_distinction() -> None:
    assert (
        resolve_workbench_state(
            lifecycle="AWARDED",
            empty_hypothesis_status=None,
            commercial_window_closed=True,
            has_candidates=True,
        )
        == WorkbenchCommercialState.COMMERCIAL_WINDOW_CLOSED
    )
    assert (
        resolve_workbench_state(
            lifecycle="OPEN",
            empty_hypothesis_status="NO_COMMERCIAL_ENTRY",
            has_candidates=False,
        )
        == WorkbenchCommercialState.NO_COMMERCIAL_ENTRY
    )
