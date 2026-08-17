"""Medal lineage: initial qualification, confirmed base, current effective.

Time-only reevaluation uses persisted semantic hypotheses + current clocks.
Never calls Qwen. Never overwrites candidate_initial_* or confirmed_base_*.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.domain.commercial_routing_v3 import CandidateMedal
from src.services.commercial_routing_v3.candidate_scoring import (
    CANDIDATE_SCORING_VERSION,
    CandidateScoringContext,
    medal_from_score,
    score_hypothesis,
)
from src.services.commercial_routing_v3.manager_object_ranking import (
    WorkbenchCommercialState,
    commercial_window_closed_reason,
)

MEDAL_LINEAGE_VERSION = "v1_lineage_20260814"
INITIAL_PROVENANCE_FIRST = "FIRST_ACCEPTANCE"
INITIAL_PROVENANCE_UNAVAILABLE = "NOT_HISTORICALLY_AVAILABLE"

REASON_ACTIVE_DECAY = "ACTIVE_TIMING_DECAY"
REASON_AWARDED_DECAY = "POST_AWARD_TIMING_DECAY"
REASON_OPEN_TO_AWARDED = "LIFECYCLE_OPEN_TO_AWARDED"
REASON_DOCUMENT_CONFIRMATION = "DOCUMENT_CONFIRMATION"
REASON_DOCUMENT_REJECTION = "DOCUMENT_REJECTION"
REASON_SOURCE_CHANGE = "SOURCE_DATA_CHANGE"
REASON_SCORING_VERSION = "SCORING_VERSION_CHANGE"

_TIME_ONLY = {REASON_ACTIVE_DECAY, REASON_AWARDED_DECAY}

_MEDAL_RANK = {
    CandidateMedal.GOLD: 4,
    CandidateMedal.SILVER: 3,
    CandidateMedal.BRONZE: 2,
    CandidateMedal.WOOD: 1,
}


def _medal(raw: Any) -> CandidateMedal:
    try:
        return CandidateMedal(str(raw or CandidateMedal.WOOD.value).upper())
    except ValueError:
        return CandidateMedal.WOOD


def _now_iso(now: Optional[datetime] = None) -> str:
    ts = now or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


def semantic_hypothesis_freeze(hypothesis: Dict[str, Any]) -> Dict[str, Any]:
    """Fields needed to rescore later without Qwen. No timing/medal."""
    return {
        "category_code": hypothesis.get("category_code")
        or hypothesis.get("commercial_category_code")
        or hypothesis.get("category"),
        "subcategory_code": hypothesis.get("subcategory_code")
        or hypothesis.get("commercial_subcategory_code"),
        "opportunity_track": hypothesis.get("opportunity_track") or hypothesis.get("track"),
        "evidence_role": hypothesis.get("evidence_role"),
        "confirmation_required": hypothesis.get("confirmation_required"),
        "confidence": hypothesis.get("confidence") or hypothesis.get("category_confidence"),
        "direct_product_evidence_sources": hypothesis.get("direct_product_evidence_sources"),
    }


@dataclass
class MedalLineage:
    candidate_initial_score: Optional[float] = None
    candidate_initial_medal: Optional[str] = None
    candidate_initial_at: Optional[str] = None
    candidate_initial_scoring_version: Optional[str] = None
    initial_medal_provenance: str = INITIAL_PROVENANCE_UNAVAILABLE
    confirmed_base_score: Optional[float] = None
    confirmed_base_medal: Optional[str] = None
    confirmed_at: Optional[str] = None
    confirmed_scoring_version: Optional[str] = None
    current_effective_score: Optional[float] = None
    current_effective_medal: Optional[str] = None
    current_effective_at: Optional[str] = None
    current_effective_reason: Optional[str] = None
    semantic_hypothesis: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "candidate_initial_score": self.candidate_initial_score,
            "candidate_initial_medal": self.candidate_initial_medal,
            "candidate_initial_at": self.candidate_initial_at,
            "candidate_initial_scoring_version": self.candidate_initial_scoring_version,
            "initial_medal_provenance": self.initial_medal_provenance,
            "confirmed_base_score": self.confirmed_base_score,
            "confirmed_base_medal": self.confirmed_base_medal,
            "confirmed_at": self.confirmed_at,
            "confirmed_scoring_version": self.confirmed_scoring_version,
            "current_effective_score": self.current_effective_score,
            "current_effective_medal": self.current_effective_medal,
            "current_effective_at": self.current_effective_at,
            "current_effective_reason": self.current_effective_reason,
            "semantic_hypothesis": self.semantic_hypothesis,
            "medal_lineage_version": MEDAL_LINEAGE_VERSION,
        }


def lineage_from_mapping(row: Optional[Dict[str, Any]]) -> MedalLineage:
    row = row or {}
    hyp = row.get("semantic_hypothesis")
    if isinstance(hyp, str):
        hyp = {}
    return MedalLineage(
        candidate_initial_score=_as_float(row.get("candidate_initial_score")),
        candidate_initial_medal=row.get("candidate_initial_medal"),
        candidate_initial_at=row.get("candidate_initial_at"),
        candidate_initial_scoring_version=row.get("candidate_initial_scoring_version"),
        initial_medal_provenance=str(
            row.get("initial_medal_provenance") or INITIAL_PROVENANCE_UNAVAILABLE
        ),
        confirmed_base_score=_as_float(row.get("confirmed_base_score")),
        confirmed_base_medal=row.get("confirmed_base_medal"),
        confirmed_at=row.get("confirmed_at"),
        confirmed_scoring_version=row.get("confirmed_scoring_version"),
        current_effective_score=_as_float(row.get("current_effective_score")),
        current_effective_medal=row.get("current_effective_medal"),
        current_effective_at=row.get("current_effective_at"),
        current_effective_reason=row.get("current_effective_reason"),
        semantic_hypothesis=dict(hyp) if isinstance(hyp, dict) else {},
    )


def first_acceptance_lineage(
    hypothesis: Dict[str, Any],
    *,
    score: float,
    medal: str,
    scoring_version: str = CANDIDATE_SCORING_VERSION,
    now: Optional[datetime] = None,
) -> MedalLineage:
    ts = _now_iso(now)
    return MedalLineage(
        candidate_initial_score=float(score),
        candidate_initial_medal=str(medal),
        candidate_initial_at=ts,
        candidate_initial_scoring_version=scoring_version,
        initial_medal_provenance=INITIAL_PROVENANCE_FIRST,
        current_effective_score=float(score),
        current_effective_medal=str(medal),
        current_effective_at=ts,
        current_effective_reason="FIRST_ACCEPTANCE",
        semantic_hypothesis=semantic_hypothesis_freeze(hypothesis),
    )


def _as_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _clamp_time_only(
    *,
    new_score: float,
    new_medal: CandidateMedal,
    prev_score: Optional[float],
    prev_medal: Optional[str],
) -> Tuple[float, CandidateMedal]:
    if prev_score is None or not prev_medal:
        return new_score, new_medal
    prev_m = _medal(prev_medal)
    score = new_score
    medal = new_medal
    if score > prev_score:
        score = prev_score
        medal = prev_m
    if _MEDAL_RANK[medal] > _MEDAL_RANK[prev_m]:
        medal = prev_m
        score = prev_score
    return score, medal


def history_row(
    *,
    procurement_id: Any,
    category: Optional[str],
    track: Optional[str],
    previous_score: Optional[float],
    previous_medal: Optional[str],
    new_score: float,
    new_medal: str,
    reason: str,
    evaluated_at: str,
    lifecycle: str,
    timing_phase: Optional[str],
    scoring_version: str,
) -> Optional[Dict[str, Any]]:
    if previous_medal == new_medal and previous_score == new_score:
        return None
    return {
        "procurement_id": procurement_id,
        "commercial_category_code": category,
        "opportunity_track": track,
        "previous_effective_score": previous_score,
        "previous_effective_medal": previous_medal,
        "new_effective_score": new_score,
        "new_effective_medal": new_medal,
        "reason": reason,
        "evaluated_at": evaluated_at,
        "lifecycle": lifecycle,
        "timing_phase": timing_phase,
        "scoring_version": scoring_version,
    }


def recalculate_current_effective_priority(
    lineage: MedalLineage,
    ctx: CandidateScoringContext,
    *,
    reason: str,
    procurement_id: Any = None,
    now: Optional[datetime] = None,
    as_of: Optional[date] = None,
) -> Tuple[MedalLineage, Optional[Dict[str, Any]], int]:
    """Rescore from frozen semantics + current clocks. qwen_calls always 0."""
    del as_of
    qwen_calls = 0
    hyp = dict(lineage.semantic_hypothesis or {})
    if not hyp.get("category_code"):
        return lineage, None, qwen_calls
    result = score_hypothesis(hyp, ctx)
    new_score = float(result.final_score)
    new_medal = result.candidate_medal
    if reason in _TIME_ONLY:
        new_score, new_medal = _clamp_time_only(
            new_score=new_score,
            new_medal=new_medal,
            prev_score=lineage.current_effective_score,
            prev_medal=lineage.current_effective_medal,
        )
    ts = _now_iso(now)
    prev_score = lineage.current_effective_score
    prev_medal = lineage.current_effective_medal
    hist = history_row(
        procurement_id=procurement_id,
        category=hyp.get("category_code"),
        track=hyp.get("opportunity_track"),
        previous_score=prev_score,
        previous_medal=prev_medal,
        new_score=new_score,
        new_medal=new_medal.value,
        reason=reason,
        evaluated_at=ts,
        lifecycle=str(ctx.normalized_lifecycle or ""),
        timing_phase=(
            ctx.execution_clock.execution_phase.value
            if ctx.execution_clock is not None
            else None
        ),
        scoring_version=CANDIDATE_SCORING_VERSION,
    )
    lineage.current_effective_score = new_score
    lineage.current_effective_medal = new_medal.value
    lineage.current_effective_at = ts
    lineage.current_effective_reason = reason
    return lineage, hist, qwen_calls


def preserve_initial_on_lifecycle_change(lineage: MedalLineage) -> MedalLineage:
    """OPEN→AWARDED must not mint a second candidate_initial record."""
    return lineage


def apply_synthetic_confirmation(
    lineage: MedalLineage,
    *,
    confirmed_score: float,
    confirmed_medal: str,
    now: Optional[datetime] = None,
) -> MedalLineage:
    """Placeholder confirmation — tests only. Does not run document workers."""
    ts = _now_iso(now)
    lineage.confirmed_base_score = float(confirmed_score)
    lineage.confirmed_base_medal = str(confirmed_medal)
    lineage.confirmed_at = ts
    lineage.confirmed_scoring_version = CANDIDATE_SCORING_VERSION
    return lineage


def manager_lineage_card_fields(lineage: MedalLineage) -> Dict[str, Any]:
    current = lineage.current_effective_medal
    initial = lineage.candidate_initial_medal
    reason = None
    if initial and current and initial != current:
        reason = lineage.current_effective_reason
    return {
        "CURRENT_MEDAL": current,
        "candidate_initial_medal": initial,
        "confirmed_base_medal": lineage.confirmed_base_medal,
        "current_lower_reason": reason,
        "current_effective_score": lineage.current_effective_score,
        "candidate_initial_score": lineage.candidate_initial_score,
        "confirmed_base_score": lineage.confirmed_base_score,
    }


def ranking_medal_and_score(hypothesis: Dict[str, Any]) -> Tuple[str, float]:
    """Manager queue uses current effective, not historical initial."""
    medal = hypothesis.get("current_effective_medal") or hypothesis.get("candidate_medal")
    score = hypothesis.get("current_effective_score")
    if score is None:
        score = hypothesis.get("final_score") or hypothesis.get("candidate_score") or 0.0
    return str(medal or CandidateMedal.WOOD.value), float(score)


def workbench_after_effective(
    *,
    lifecycle: str,
    routing_mode: Optional[str],
    empty_hypothesis_status: Optional[str],
    execution_phase: Optional[str],
    hard_cap: Optional[str],
    hard_cap_reason: Optional[str],
    has_candidates: bool,
    current_effective_medal: Optional[str],
) -> Optional[str]:
    closed = commercial_window_closed_reason(
        lifecycle=lifecycle,
        routing_mode=routing_mode,
        empty_hypothesis_status=empty_hypothesis_status,
        execution_phase=execution_phase,
        hard_cap=hard_cap,
        hard_cap_reason=hard_cap_reason,
        has_candidates=has_candidates,
    )
    if closed:
        return WorkbenchCommercialState.COMMERCIAL_WINDOW_CLOSED.value
    if (
        str(lifecycle or "").upper() == "AWARDED"
        and str(current_effective_medal or "").upper() == CandidateMedal.WOOD.value
        and str(execution_phase or "").upper() == "CLOSING"
    ):
        return WorkbenchCommercialState.COMMERCIAL_WINDOW_CLOSED.value
    return None


def scoring_ctx_from_timing(
    *,
    procurement_form: str,
    routing_mode: Optional[str],
    lifecycle: str,
    object_classification: Optional[Dict[str, Any]],
    commercial_timing_value: Optional[float],
    remaining_days: Optional[float],
    execution_clock=None,
    source_origin: Optional[str] = None,
    source_data_quality: str = "OK",
    initial_price: float = 0.0,
    final_contract_price: Optional[float] = None,
) -> CandidateScoringContext:
    return CandidateScoringContext(
        procurement_form=procurement_form,
        routing_mode=routing_mode,
        normalized_lifecycle=lifecycle,
        source_origin=source_origin,
        source_data_quality=source_data_quality,
        object_classification=object_classification,
        commercial_timing_value=commercial_timing_value,
        remaining_days=remaining_days,
        execution_remaining_days=(
            execution_clock.execution_remaining_days if execution_clock is not None else None
        ),
        initial_price=initial_price,
        final_contract_price=final_contract_price,
        execution_clock=execution_clock,
    )
