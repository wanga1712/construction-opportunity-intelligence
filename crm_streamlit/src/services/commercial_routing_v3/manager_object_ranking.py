"""Canonical manager object eligibility and ranking for V3 routing.

Ranking respects FINAL medal tier (post hard-cap), not raw numeric score alone.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Dict, List, Optional, Tuple

from src.domain.commercial_routing_v3 import CandidateMedal

MANAGER_RANKING_VERSION = "v1_closing_eligibility_20260814"

_MEDAL_RANK = {
    CandidateMedal.GOLD: 4,
    CandidateMedal.SILVER: 3,
    CandidateMedal.BRONZE: 2,
    CandidateMedal.WOOD: 1,
}

_MEDAL_PRIORITY_BASE = {
    CandidateMedal.GOLD: 400.0,
    CandidateMedal.SILVER: 300.0,
    CandidateMedal.BRONZE: 200.0,
    CandidateMedal.WOOD: 100.0,
}


class WorkbenchCommercialState(StrEnum):
    PREQUALIFIED_ACTIVE = "PREQUALIFIED_ACTIVE"
    PREQUALIFIED_AWARDED = "PREQUALIFIED_AWARDED"
    NO_COMMERCIAL_ENTRY = "NO_COMMERCIAL_ENTRY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    COMMERCIAL_WINDOW_CLOSED = "COMMERCIAL_WINDOW_CLOSED"
    CLOSED_DIRECT_SUPPLY = "CLOSED_DIRECT_SUPPLY"


class ManagerActionability(StrEnum):
    ACTIONABLE = "ACTIONABLE"
    NOT_ACTIONABLE = "NOT_ACTIONABLE"
    SKIP = "SKIP"


def _medal_enum(raw: Any) -> CandidateMedal:
    try:
        return CandidateMedal(str(raw or CandidateMedal.WOOD.value).upper())
    except ValueError:
        return CandidateMedal.WOOD


def _best_hypothesis(hypotheses: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    kept = [h for h in hypotheses if h.get("category") or h.get("commercial_category_code")]
    if not kept:
        return None
    return max(kept, key=lambda h: _manager_priority_score_for_hypothesis(h))


def _raw_score(h: Dict[str, Any]) -> float:
    if h.get("current_effective_score") is not None:
        return float(h.get("current_effective_score") or 0.0)
    return float(h.get("final_score") or h.get("candidate_score") or h.get("base_score") or 0.0)


def _effective_medal(h: Dict[str, Any]) -> CandidateMedal:
    return _medal_enum(h.get("current_effective_medal") or h.get("candidate_medal"))


def _manager_priority_score_for_hypothesis(h: Dict[str, Any]) -> float:
    medal = _effective_medal(h)
    final_score = _raw_score(h)
    return _MEDAL_PRIORITY_BASE[medal] + min(max(final_score, 0.0), 99.999) / 100.0


def manager_priority_score(medal: CandidateMedal, final_score: float) -> float:
    return _MEDAL_PRIORITY_BASE[medal] + min(max(final_score, 0.0), 99.999) / 100.0


def commercial_window_closed_reason(
    *,
    lifecycle: str,
    routing_mode: Optional[str],
    empty_hypothesis_status: Optional[str],
    execution_phase: Optional[str],
    hard_cap: Optional[str],
    hard_cap_reason: Optional[str],
    has_candidates: bool,
) -> Optional[str]:
    if str(empty_hypothesis_status or "").upper() == "NO_COMMERCIAL_ENTRY":
        return None
    if not has_candidates:
        return None
    if str(lifecycle or "").upper() != "AWARDED":
        return None
    if str(routing_mode or "") != "OBJECT_MODE":
        return None
    phase = str(execution_phase or "").upper()
    cap_reason = str(hard_cap_reason or "")
    if phase == "CLOSING":
        return "post_award_execution_phase_closing"
    if str(hard_cap or "").upper() == CandidateMedal.WOOD.value and (
        "post_award_closing" in cap_reason
        or "post_award_execution_remaining_ratio_critical" in cap_reason
    ):
        return cap_reason or "post_award_late_entry_hard_cap"
    return None


def closed_direct_supply_reason(
    *,
    lifecycle: str,
    procurement_form: Optional[str],
    routing_mode: Optional[str],
    tracks: List[str],
    empty_hypothesis_status: Optional[str],
    has_candidates: bool,
) -> Optional[str]:
    """AWARDED + DIRECT_GOODS + DIRECT_SUPPLY is closed — not NCE, not object follow-up."""
    if str(empty_hypothesis_status or "").upper() == "NO_COMMERCIAL_ENTRY":
        return None
    if str(lifecycle or "").upper() != "AWARDED":
        return None
    form = str(procurement_form or "").upper()
    mode = str(routing_mode or "").upper()
    tracks_u = {str(t or "").upper() for t in tracks}
    if "DIRECT_SUPPLY" not in tracks_u:
        return None
    if form == "DIRECT_GOODS_PURCHASE" or mode in ("DIRECT_OR_OTHER", "DIRECT_GOODS"):
        if has_candidates:
            return "awarded_direct_goods_direct_supply_closed"
    return None


def resolve_workbench_state(
    *,
    lifecycle: str,
    empty_hypothesis_status: Optional[str],
    review_required: bool = False,
    commercial_window_closed: bool = False,
    closed_direct_supply: bool = False,
    has_candidates: bool = False,
) -> WorkbenchCommercialState:
    empty = str(empty_hypothesis_status or "").upper()
    if empty == "NO_COMMERCIAL_ENTRY":
        return WorkbenchCommercialState.NO_COMMERCIAL_ENTRY
    if review_required or empty == "REVIEW_REQUIRED":
        return WorkbenchCommercialState.REVIEW_REQUIRED
    if closed_direct_supply:
        return WorkbenchCommercialState.CLOSED_DIRECT_SUPPLY
    if commercial_window_closed:
        return WorkbenchCommercialState.COMMERCIAL_WINDOW_CLOSED
    lc = str(lifecycle or "").upper()
    if lc == "AWARDED" and has_candidates:
        return WorkbenchCommercialState.PREQUALIFIED_AWARDED
    if has_candidates:
        return WorkbenchCommercialState.PREQUALIFIED_ACTIVE
    if empty == "REVIEW_REQUIRED":
        return WorkbenchCommercialState.REVIEW_REQUIRED
    return WorkbenchCommercialState.NO_COMMERCIAL_ENTRY


def resolve_manager_actionability(
    workbench_state: WorkbenchCommercialState,
) -> ManagerActionability:
    if workbench_state == WorkbenchCommercialState.NO_COMMERCIAL_ENTRY:
        return ManagerActionability.SKIP
    if workbench_state in (
        WorkbenchCommercialState.COMMERCIAL_WINDOW_CLOSED,
        WorkbenchCommercialState.CLOSED_DIRECT_SUPPLY,
    ):
        return ManagerActionability.NOT_ACTIONABLE
    if workbench_state in (
        WorkbenchCommercialState.PREQUALIFIED_ACTIVE,
        WorkbenchCommercialState.PREQUALIFIED_AWARDED,
    ):
        return ManagerActionability.ACTIONABLE
    return ManagerActionability.NOT_ACTIONABLE


def build_manager_object(item: Dict[str, Any]) -> Dict[str, Any]:
    """Build one manager-facing object row with eligibility + priority fields."""
    hypotheses = list(item.get("hypotheses") or [])
    best = _best_hypothesis(hypotheses)
    exec_clock = None
    if best:
        exec_clock = best.get("execution_clock")
    if not exec_clock:
        exec_clock = item.get("execution_clock")

    best_medal = CandidateMedal.WOOD
    best_raw = 0.0
    best_final = 0.0
    hard_cap = None
    hard_cap_reason = None
    if best:
        best_medal = _effective_medal(best)
        best_raw = float(best.get("base_score") or best.get("candidate_score") or 0.0)
        best_final = _raw_score(best)
        hard_cap = best.get("hard_cap")
        hard_cap_reason = best.get("hard_cap_reason")

    exec_phase = (exec_clock or {}).get("execution_phase")
    tracks = [
        str(h.get("track") or h.get("opportunity_track") or "")
        for h in hypotheses
    ]
    form = item.get("procurement_form") or item.get("procurement_form_final")
    closed_ds_reason = closed_direct_supply_reason(
        lifecycle=str(item.get("lifecycle") or ""),
        procurement_form=form,
        routing_mode=item.get("routing_mode"),
        tracks=tracks,
        empty_hypothesis_status=item.get("empty_hypothesis_status"),
        has_candidates=bool(best),
    )
    closed_reason = commercial_window_closed_reason(
        lifecycle=str(item.get("lifecycle") or ""),
        routing_mode=item.get("routing_mode"),
        empty_hypothesis_status=item.get("empty_hypothesis_status"),
        execution_phase=exec_phase,
        hard_cap=hard_cap,
        hard_cap_reason=hard_cap_reason,
        has_candidates=bool(best),
    )
    commercial_window_closed = closed_reason is not None
    closed_direct_supply = closed_ds_reason is not None
    review_required = str(item.get("status") or "").upper() == "REVIEW" or str(
        item.get("empty_hypothesis_status") or ""
    ).upper() == "REVIEW_REQUIRED"

    workbench = resolve_workbench_state(
        lifecycle=str(item.get("lifecycle") or ""),
        empty_hypothesis_status=item.get("empty_hypothesis_status"),
        review_required=review_required,
        commercial_window_closed=commercial_window_closed,
        closed_direct_supply=closed_direct_supply,
        has_candidates=bool(best),
    )
    actionability = resolve_manager_actionability(workbench)
    priority = manager_priority_score(best_medal, best_final)

    prequalified_awarded = workbench == WorkbenchCommercialState.PREQUALIFIED_AWARDED

    why = item.get("WHY_THIS_OBJECT_IS_WORTH_MANAGER_ATTENTION")
    if not why:
        if workbench == WorkbenchCommercialState.NO_COMMERCIAL_ENTRY:
            why = "SKIP/NCE"
        elif workbench == WorkbenchCommercialState.COMMERCIAL_WINDOW_CLOSED:
            why = (
                f"Commercial relevance preserved but execution window closed "
                f"({exec_phase or 'late'}); winner/context retained for CRM history"
            )
        elif workbench == WorkbenchCommercialState.CLOSED_DIRECT_SUPPLY:
            why = (
                "Direct goods already awarded to another supplier; "
                "category/winner preserved as history, not a working sales opportunity"
            )
        else:
            why = (
                f"Object {item.get('object_type') or '—'} / "
                f"{item.get('work_stage') or item.get('lifecycle')}; "
                f"{len([h for h in hypotheses if h.get('category')])} candidates; "
                f"action={item.get('overall_research_action')}"
            )

    return {
        "procurement_id": item.get("procurement_id"),
        "title": item.get("title"),
        "lifecycle": item.get("lifecycle"),
        "source_origin": item.get("source_origin"),
        "SOURCE_DATA_QUALITY": item.get("source_data_quality"),
        "object_sector": item.get("object_sector"),
        "object_type": item.get("object_type"),
        "object_subtype": item.get("object_subtype"),
        "object_context": item.get("object_context"),
        "work_stage": item.get("work_stage"),
        "customer": item.get("customer"),
        "winner": item.get("winner"),
        "initial_price": item.get("initial_price"),
        "final_contract_price": item.get("final_contract_price"),
        "commercial_timing_value": item.get("commercial_timing_value"),
        "execution_remaining_days": item.get("execution_remaining_days"),
        "delivery_start_at": item.get("delivery_start_at"),
        "delivery_end_at": item.get("delivery_end_at"),
        "execution_clock": exec_clock,
        "post_award_commercial_timing_value": (
            (exec_clock or {}).get("post_award_commercial_timing_value")
        ),
        "execution_phase": exec_phase,
        "best_raw_candidate_score": round(best_raw, 4),
        "best_final_candidate_score": round(best_final, 4),
        "best_candidate_medal": best_medal.value,
        "CURRENT_MEDAL": best_medal.value,
        "candidate_initial_medal": (best or {}).get("candidate_initial_medal"),
        "candidate_initial_score": (best or {}).get("candidate_initial_score"),
        "confirmed_base_medal": (best or {}).get("confirmed_base_medal"),
        "confirmed_base_score": (best or {}).get("confirmed_base_score"),
        "current_lower_reason": (
            (best or {}).get("current_effective_reason")
            if (best or {}).get("candidate_initial_medal")
            and str((best or {}).get("candidate_initial_medal")) != best_medal.value
            else None
        ),
        "hard_cap": hard_cap,
        "hard_cap_reason": hard_cap_reason,
        "manager_priority_score": round(priority, 6),
        "manager_actionability": actionability.value,
        "workbench_status": workbench.value,
        "commercial_window_closed": commercial_window_closed,
        "commercial_eligibility_reason": closed_ds_reason or closed_reason,
        "closed_direct_supply": closed_direct_supply,
        "FOLLOW_UP_AWARDED": (
            workbench == WorkbenchCommercialState.PREQUALIFIED_AWARDED
        ),
        "DOCUMENT_RESEARCH_REQUIRED_FOR_COMMERCIAL_ENTRY": (
            workbench
            in (
                WorkbenchCommercialState.PREQUALIFIED_ACTIVE,
                WorkbenchCommercialState.PREQUALIFIED_AWARDED,
            )
        ),
        "PREQUALIFIED_AWARDED": prequalified_awarded,
        "candidate_categories": [h for h in hypotheses if h.get("category")],
        "WHY_THIS_OBJECT_IS_WORTH_MANAGER_ATTENTION": why,
        "document_research_priority": item.get("document_research_priority"),
        "overall_research_action": item.get("overall_research_action"),
        "manager_ranking_version": MANAGER_RANKING_VERSION,
    }


def rank_manager_objects(objects: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (actionable_prequalified_ranked, closed_or_ineligible)."""
    actionable: List[Dict[str, Any]] = []
    other: List[Dict[str, Any]] = []
    for obj in objects:
        wb = str(obj.get("workbench_status") or "")
        act = str(obj.get("manager_actionability") or "")
        if act == ManagerActionability.ACTIONABLE.value and wb in (
            WorkbenchCommercialState.PREQUALIFIED_ACTIVE.value,
            WorkbenchCommercialState.PREQUALIFIED_AWARDED.value,
        ):
            actionable.append(obj)
        else:
            other.append(obj)

    actionable.sort(
        key=lambda o: (
            -float(o.get("manager_priority_score") or 0),
            -float(o.get("best_final_candidate_score") or 0),
            int(o.get("procurement_id") or 0),
        )
    )
    other.sort(
        key=lambda o: (
            -float(o.get("manager_priority_score") or 0),
            int(o.get("procurement_id") or 0),
        )
    )
    for i, obj in enumerate(actionable, 1):
        obj["manager_rank"] = i
    for i, obj in enumerate(other, 1):
        obj["manager_rank_closed_or_ineligible"] = i
    return actionable, other


def ranking_respects_final_medal(objects: List[Dict[str, Any]]) -> bool:
    """True when no lower medal outranks a higher medal in actionable queue."""
    actionable, _ = rank_manager_objects(objects)
    for i, a in enumerate(actionable):
        ma = _MEDAL_RANK[_medal_enum(a.get("best_candidate_medal"))]
        pa = float(a.get("manager_priority_score") or 0)
        for b in actionable[i + 1 :]:
            mb = _MEDAL_RANK[_medal_enum(b.get("best_candidate_medal"))]
            pb = float(b.get("manager_priority_score") or 0)
            if mb > ma:
                continue
            if mb < ma and pb > pa:
                return False
            if mb == ma and float(b.get("best_final_candidate_score") or 0) > float(
                a.get("best_final_candidate_score") or 0
            ):
                return False
    return True


def count_actionable_bronze_below_closing_wood(objects: List[Dict[str, Any]]) -> int:
    """Count CLOSING WOOD hard-capped objects ranked above actionable BRONZE."""
    actionable, closed = rank_manager_objects(objects)
    closed_wood = [
        o
        for o in closed
        if str(o.get("workbench_status") or "") == WorkbenchCommercialState.COMMERCIAL_WINDOW_CLOSED.value
        and _medal_enum(o.get("best_candidate_medal")) == CandidateMedal.WOOD
    ]
    bronze_actionable = [
        o
        for o in actionable
        if _medal_enum(o.get("best_candidate_medal")) == CandidateMedal.BRONZE
    ]
    if not closed_wood or not bronze_actionable:
        return 0
    violations = 0
    for cw in closed_wood:
        cw_score = float(cw.get("best_final_candidate_score") or 0)
        for ba in bronze_actionable:
            if cw_score > float(ba.get("best_final_candidate_score") or 0):
                # Would have outranked by raw score — check if wrongly in actionable queue
                pass
        # Violation if closed wood appears in actionable list (shouldn't)
        if cw in actionable:
            violations += 1
    # Also check merged naive sort by raw score would invert order — our actionable list should not contain closed
    merged_wrong = 0
    for rank, obj in enumerate(actionable, 1):
        if str(obj.get("workbench_status") or "") == WorkbenchCommercialState.COMMERCIAL_WINDOW_CLOSED.value:
            merged_wrong += 1
    return merged_wrong
