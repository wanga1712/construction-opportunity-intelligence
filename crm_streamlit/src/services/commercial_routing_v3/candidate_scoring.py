"""Canonical deterministic Candidate scoring authority for V3 routing.

Single production path:
  raw hypothesis semantics → score components → base_score → adjustments → final_score → medal

Model/Qwen must NOT set final medal or score; normalizer strips model values.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from src.domain.commercial_routing_v3 import (
    CandidateMedal,
    OpportunityTrack,
    ProcurementForm,
)
from src.services.commercial_routing_v3.post_award_execution_timing import (
    ExecutionClock,
    ExecutionPhase,
    category_execution_phase_fit,
    clock_from_model_input,
    clock_to_audit_dict,
    late_entry_hard_cap,
)

CANDIDATE_SCORING_VERSION = "v2_post_award_execution_20260814"

MEDAL_THRESHOLDS: Dict[CandidateMedal, float] = {
    CandidateMedal.GOLD: 75.0,
    CandidateMedal.SILVER: 50.0,
    CandidateMedal.BRONZE: 25.0,
}

_MEDAL_RANK = {
    CandidateMedal.GOLD: 4,
    CandidateMedal.SILVER: 3,
    CandidateMedal.BRONZE: 2,
    CandidateMedal.WOOD: 1,
}

_OKPD_LIKE = re.compile(r"^\d{2}(\.\d+)*$")

# Object type → category → fit (0–100). Generic object-mode priors.
_OBJECT_CATEGORY_FIT: Dict[Tuple[str, str], float] = {
    ("SCHOOL", "flooring"): 88.0,
    ("SCHOOL", "waterproofing"): 85.0,
    ("SCHOOL", "lighting"): 72.0,
    ("SCHOOL", "drainage_water_management"): 58.0,
    ("ROAD", "drainage_water_management"): 88.0,
    ("ROAD", "curbstone"): 82.0,
    ("ROAD", "lighting"): 68.0,
    ("ROAD", "waterproofing"): 52.0,
    ("ROAD", "composite_structures"): 48.0,
    ("GAS_PIPELINE", "composite_structures"): 55.0,
    ("BUILDING_OR_STRUCTURE", "waterproofing"): 60.0,
    ("BUILDING_OR_STRUCTURE", "flooring"): 58.0,
    ("BUILDING_OR_STRUCTURE", "lighting"): 55.0,
}

_EVIDENCE_ROLE_FACTOR: Dict[str, float] = {
    "COMMERCIAL_PRODUCT_PRIOR": 1.0,
    "DIRECT_CATEGORY_EVIDENCE": 0.98,
    "CONTEXTUAL_RESEARCH_PRIOR": 0.82,
    "SIGNAL_ONLY": 0.65,
}

_TRACK_ACTIONABILITY: Dict[str, float] = {
    OpportunityTrack.DIRECT_SUPPLY.value: 85.0,
    OpportunityTrack.EMBEDDED_MATERIAL.value: 72.0,
    OpportunityTrack.DESIGN_REQUIREMENT.value: 78.0,
    OpportunityTrack.DESIGN_INFLUENCE.value: 70.0,
}


@dataclass
class CandidateScoringContext:
    procurement_form: str
    routing_mode: Optional[str] = None
    normalized_lifecycle: str = "OPEN"
    source_origin: Optional[str] = None
    source_data_quality: str = "OK"
    object_classification: Optional[Dict[str, Any]] = None
    commercial_timing_value: Optional[float] = None
    execution_remaining_days: Optional[float] = None
    remaining_days: Optional[float] = None
    deadline_pressure: Optional[float] = None
    initial_price: float = 0.0
    final_contract_price: Optional[float] = None
    category_confidence: float = 0.0
    execution_clock: Optional[ExecutionClock] = None


@dataclass
class CandidateScoringResult:
    base_score: float
    final_score: float
    candidate_medal: CandidateMedal
    score_components: Dict[str, float] = field(default_factory=dict)
    boost_reasons: List[str] = field(default_factory=list)
    downgrade_reasons: List[str] = field(default_factory=list)
    hard_cap: Optional[str] = None
    hard_cap_reason: Optional[str] = None
    timing_component_status: str = "NOT_AVAILABLE"
    execution_timing_status: str = "NOT_AVAILABLE"
    candidate_scoring_version: str = CANDIDATE_SCORING_VERSION
    execution_audit: Optional[Dict[str, Any]] = None


def looks_like_okpd_category_code(code: str) -> bool:
    c = str(code or "").strip()
    return bool(_OKPD_LIKE.match(c))


def medal_from_score(
    score: float,
    *,
    hard_cap: Optional[CandidateMedal] = None,
    hard_cap_reason: Optional[str] = None,
) -> Tuple[CandidateMedal, Optional[str], Optional[str]]:
    s = float(score)
    if s >= MEDAL_THRESHOLDS[CandidateMedal.GOLD]:
        medal = CandidateMedal.GOLD
    elif s >= MEDAL_THRESHOLDS[CandidateMedal.SILVER]:
        medal = CandidateMedal.SILVER
    elif s >= MEDAL_THRESHOLDS[CandidateMedal.BRONZE]:
        medal = CandidateMedal.BRONZE
    else:
        medal = CandidateMedal.WOOD
    if hard_cap and _MEDAL_RANK[medal] > _MEDAL_RANK[hard_cap]:
        return hard_cap, hard_cap.name, hard_cap_reason
    return medal, None, None


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _parse_timing_value(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().upper()
    if s in ("HIGH", "H"):
        return 85.0
    if s in ("MEDIUM", "MED", "M"):
        return 55.0
    if s in ("LOW", "L"):
        return 25.0
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def _object_category_fit(
    category: str,
    obj: Optional[Dict[str, Any]],
) -> float:
    if not obj:
        return 45.0
    obj_type = str(obj.get("object_type") or "").upper()
    key = (obj_type, category)
    if key in _OBJECT_CATEGORY_FIT:
        return _OBJECT_CATEGORY_FIT[key]
    sector = str(obj.get("object_sector") or "")
    if sector and category in ("waterproofing", "lighting", "flooring"):
        return 50.0
    return 40.0


def _awarded_timing_score(
    ctx: CandidateScoringContext,
    category: str,
) -> Tuple[float, str, str]:
    clock = ctx.execution_clock
    if clock is None:
        return 35.0, "NOT_AVAILABLE", "NOT_AVAILABLE"
    exec_status = clock.execution_timing_status
    if exec_status == "SUPPRESSED_SOURCE_SUSPECT":
        return 32.0, "SUPPRESSED_SOURCE_SUSPECT", exec_status
    if clock.post_award_commercial_timing_value is None:
        return 35.0, "NOT_AVAILABLE", exec_status
    phase_fit = category_execution_phase_fit(category, clock.execution_phase)
    score = _clamp(float(clock.post_award_commercial_timing_value) * phase_fit)
    return score, "USED", exec_status


def _commercial_timing_score(
    ctx: CandidateScoringContext,
    *,
    category: str = "",
) -> Tuple[float, str, str]:
    suspect = str(ctx.source_data_quality or "").upper() == "SUSPECT"
    lc = str(ctx.normalized_lifecycle or "").upper()
    timing_raw = _parse_timing_value(ctx.commercial_timing_value)

    if lc == "AWARDED":
        return _awarded_timing_score(ctx, category)

    if suspect and timing_raw is not None:
        return 35.0, "SUPPRESSED_SOURCE_SUSPECT", "NOT_AVAILABLE"

    rem = ctx.remaining_days
    if rem is not None and float(rem) < 0:
        return 10.0, "USED", "NOT_AVAILABLE"
    if rem is not None and float(rem) < 3:
        return 20.0, "USED", "NOT_AVAILABLE"
    if timing_raw is not None:
        return _clamp(timing_raw), "USED", "NOT_AVAILABLE"
    if rem is not None:
        r = float(rem)
        if r >= 14:
            return 60.0, "USED", "NOT_AVAILABLE"
        if r >= 3:
            return 45.0, "USED", "NOT_AVAILABLE"
    return 35.0, "NOT_AVAILABLE", "NOT_AVAILABLE"


def _commercial_scale_score(ctx: CandidateScoringContext) -> float:
    price = ctx.final_contract_price or ctx.initial_price
    try:
        p = float(price or 0)
    except (TypeError, ValueError):
        p = 0.0
    if p <= 0:
        return 30.0
    # Log-scaled; never alone pushes to Gold (weight is only 15%)
    return _clamp(35.0 + 8.0 * math.log10(max(p, 100_000.0)), hi=88.0)


def _source_confidence_score(ctx: CandidateScoringContext) -> float:
    if str(ctx.source_data_quality or "").upper() == "SUSPECT":
        return 55.0
    if str(ctx.source_origin or "").upper() == "UNKNOWN":
        return 60.0
    return 85.0


def _stage_actionability(
    track: str,
    form: str,
    lc: str,
    *,
    execution_phase: Optional[ExecutionPhase] = None,
) -> float:
    base = _TRACK_ACTIONABILITY.get(track, 50.0)
    if track == OpportunityTrack.EMBEDDED_MATERIAL.value:
        if lc == "AWARDED":
            if execution_phase in (
                ExecutionPhase.CLOSING,
                ExecutionPhase.LATE_EXECUTION,
            ):
                return max(55.0, base - 12.0)
            if execution_phase == ExecutionPhase.MID_EXECUTION:
                return base
            if execution_phase == ExecutionPhase.EARLY_EXECUTION:
                return min(88.0, base + 8.0)
            return base
        if form in (
            ProcurementForm.CONSTRUCTION_WORKS.value,
            ProcurementForm.DESIGN_AND_BUILD.value,
        ):
            return base
    if track == OpportunityTrack.DIRECT_SUPPLY.value:
        return 80.0
    return base


def _evidence_role_factor(role: str, confirmation_required: bool) -> float:
    factor = _EVIDENCE_ROLE_FACTOR.get(str(role or "").upper(), 0.75)
    # confirmation_required does NOT force WOOD — slight neutral factor
    if confirmation_required and role == "CONTEXTUAL_RESEARCH_PRIOR":
        return factor
    return factor


def score_hypothesis(
    hypothesis: Dict[str, Any],
    ctx: CandidateScoringContext,
) -> CandidateScoringResult:
    """Deterministic final Candidate score + medal for one hypothesis."""
    category = str(hypothesis.get("category_code") or "")
    track = str(hypothesis.get("opportunity_track") or OpportunityTrack.UNKNOWN.value)
    role = str(hypothesis.get("evidence_role") or "CONTEXTUAL_RESEARCH_PRIOR")
    confirmation = bool(hypothesis.get("confirmation_required"))
    conf = float(hypothesis.get("confidence") or hypothesis.get("category_confidence") or 0.0)
    ctx = CandidateScoringContext(
        procurement_form=ctx.procurement_form,
        routing_mode=ctx.routing_mode,
        normalized_lifecycle=ctx.normalized_lifecycle,
        source_origin=ctx.source_origin,
        source_data_quality=ctx.source_data_quality,
        object_classification=ctx.object_classification,
        commercial_timing_value=ctx.commercial_timing_value,
        execution_remaining_days=ctx.execution_remaining_days,
        remaining_days=ctx.remaining_days,
        deadline_pressure=ctx.deadline_pressure,
        initial_price=ctx.initial_price,
        final_contract_price=ctx.final_contract_price,
        category_confidence=conf,
        execution_clock=ctx.execution_clock,
    )

    obj_fit = _object_category_fit(category, ctx.object_classification)
    timing_score, timing_status, execution_timing_status = _commercial_timing_score(
        ctx, category=category
    )
    exec_phase = (
        ctx.execution_clock.execution_phase
        if ctx.execution_clock is not None
        else None
    )
    phase_fit = category_execution_phase_fit(category, exec_phase or ExecutionPhase.NOT_AVAILABLE)
    stage = _stage_actionability(
        track,
        ctx.procurement_form,
        ctx.normalized_lifecycle,
        execution_phase=exec_phase,
    )
    scale = _commercial_scale_score(ctx)
    source_conf = _source_confidence_score(ctx)
    evidence_factor = _evidence_role_factor(role, confirmation)

    # Confidence nudges object fit for direct supply with product evidence
    if role in ("COMMERCIAL_PRODUCT_PRIOR", "DIRECT_CATEGORY_EVIDENCE"):
        obj_fit = max(obj_fit, _clamp(conf * 100))

    base = (
        0.32 * obj_fit
        + 0.28 * timing_score
        + 0.20 * stage
        + 0.12 * scale
        + 0.08 * source_conf
    )
    base *= evidence_factor
    base = _clamp(base)

    boosts: List[str] = []
    downgrades: List[str] = []
    hard_cap: Optional[CandidateMedal] = None
    hard_cap_reason: Optional[str] = None
    final = base

    lc = str(ctx.normalized_lifecycle or "").upper()
    if lc == "AWARDED" and ctx.execution_clock is not None:
        cap, cap_reason = late_entry_hard_cap(ctx.execution_clock)
        if cap is not None:
            hard_cap = cap
            hard_cap_reason = cap_reason
            downgrades.append(cap_reason or "post_award_late_entry_cap")
        elif (
            track == OpportunityTrack.EMBEDDED_MATERIAL.value
            and exec_phase == ExecutionPhase.EARLY_EXECUTION
            and ctx.execution_clock.execution_remaining_days
            and float(ctx.execution_clock.execution_remaining_days) >= 90
        ):
            final += 4.0
            boosts.append("post_award_early_execution_runway")

    if ctx.remaining_days is not None and float(ctx.remaining_days) < 1:
        final -= 15.0
        downgrades.append("procedure_near_expiry")

    if track == OpportunityTrack.DIRECT_SUPPLY.value and role == "CONTEXTUAL_RESEARCH_PRIOR":
        hard_cap = CandidateMedal.BRONZE
        hard_cap_reason = "direct_supply_without_product_evidence"
        downgrades.append("direct_supply_contextual_cap")

    final = _clamp(final)
    medal, cap, cap_reason = medal_from_score(
        final, hard_cap=hard_cap, hard_cap_reason=hard_cap_reason
    )

    components = {
        "object_category_fit_score": round(obj_fit, 4),
        "commercial_timing_score": round(timing_score, 4),
        "stage_actionability_score": round(stage, 4),
        "commercial_scale_score": round(scale, 4),
        "source_confidence_score": round(source_conf, 4),
        "evidence_role_factor": round(evidence_factor, 4),
        "category_confidence_input": round(conf, 4),
        "category_execution_phase_fit": round(phase_fit, 4),
        "post_award_commercial_timing_value": (
            ctx.execution_clock.post_award_commercial_timing_value
            if ctx.execution_clock is not None
            else None
        ),
        "execution_phase": (
            exec_phase.value if exec_phase is not None else None
        ),
    }

    execution_audit = (
        clock_to_audit_dict(ctx.execution_clock) if ctx.execution_clock is not None else None
    )

    return CandidateScoringResult(
        base_score=round(base, 4),
        final_score=round(final, 4),
        candidate_medal=medal,
        score_components=components,
        boost_reasons=boosts,
        downgrade_reasons=downgrades,
        hard_cap=cap,
        hard_cap_reason=cap_reason,
        timing_component_status=timing_status,
        execution_timing_status=execution_timing_status,
        execution_audit=execution_audit,
    )


def apply_candidate_scoring_to_hypotheses(
    hypotheses: List[Dict[str, Any]],
    *,
    procurement: Dict[str, Any],
    normalized: Dict[str, Any],
    source_data_quality: str = "OK",
) -> List[Dict[str, Any]]:
    """Score all hypotheses; attach audit fields; medal derived ONLY from final_score."""
    mi = procurement.get("v3_model_input") if isinstance(procurement.get("v3_model_input"), dict) else {}
    try:
        price = float(procurement.get("price") or mi.get("initial_price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    try:
        final_p = float(mi.get("final_contract_price") or 0) if mi.get("final_contract_price") else None
    except (TypeError, ValueError):
        final_p = None

    lc = str(mi.get("normalized_lifecycle") or procurement.get("normalized_lifecycle") or "OPEN")
    execution_clock = None
    if lc.upper() == "AWARDED":
        execution_clock = clock_from_model_input(mi, source_data_quality=source_data_quality)

    ctx = CandidateScoringContext(
        procurement_form=str(normalized.get("procurement_form") or ""),
        routing_mode=normalized.get("routing_mode"),
        normalized_lifecycle=lc,
        source_origin=mi.get("source_origin") or procurement.get("source_origin"),
        source_data_quality=source_data_quality,
        object_classification=normalized.get("object_classification"),
        commercial_timing_value=_parse_timing_value(mi.get("commercial_timing_value")),
        execution_remaining_days=_as_float(mi.get("execution_remaining_days")),
        remaining_days=_as_float(mi.get("remaining_days")),
        deadline_pressure=_parse_timing_value(mi.get("deadline_pressure")),
        initial_price=price,
        final_contract_price=final_p,
        execution_clock=execution_clock,
    )

    out: List[Dict[str, Any]] = []
    for h in hypotheses:
        row = dict(h)
        result = score_hypothesis(row, ctx)
        row["commercial_priority_score"] = int(round(result.final_score))
        row["research_value_score"] = int(round(result.base_score))
        row["candidate_score"] = result.final_score
        row["candidate_medal"] = result.candidate_medal.value
        row["candidate_scoring_version"] = result.candidate_scoring_version
        row["base_score"] = result.base_score
        row["final_score"] = result.final_score
        row["score_components"] = result.score_components
        row["boost_reasons"] = result.boost_reasons
        row["downgrade_reasons"] = result.downgrade_reasons
        row["hard_cap"] = result.hard_cap
        row["hard_cap_reason"] = result.hard_cap_reason
        row["timing_component_status"] = result.timing_component_status
        row["execution_timing_status"] = result.execution_timing_status
        if result.execution_audit:
            row["execution_clock"] = result.execution_audit
        if not row.get("candidate_initial_medal"):
            row["candidate_initial_score"] = result.final_score
            row["candidate_initial_medal"] = result.candidate_medal.value
            row["candidate_initial_at"] = None
            row["candidate_initial_scoring_version"] = result.candidate_scoring_version
            row["initial_medal_provenance"] = "FIRST_ACCEPTANCE"
        row["current_effective_score"] = result.final_score
        row["current_effective_medal"] = result.candidate_medal.value
        row["semantic_hypothesis"] = {
            "category_code": row.get("category_code") or row.get("commercial_category_code"),
            "subcategory_code": row.get("subcategory_code") or row.get("commercial_subcategory_code"),
            "opportunity_track": row.get("opportunity_track") or row.get("track"),
            "evidence_role": row.get("evidence_role"),
            "confirmation_required": row.get("confirmation_required"),
            "confidence": row.get("confidence") or row.get("category_confidence"),
            "direct_product_evidence_sources": row.get("direct_product_evidence_sources"),
        }
        out.append(row)
    return out


def _as_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def check_medal_monotonicity(scored: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return inconsistencies where higher final_score has worse medal without hard_cap."""
    issues: List[Dict[str, Any]] = []
    rows = sorted(scored, key=lambda x: float(x.get("final_score") or 0), reverse=True)
    for i, a in enumerate(rows):
        for b in rows[i + 1 :]:
            sa = float(a.get("final_score") or 0)
            sb = float(b.get("final_score") or 0)
            if sa <= sb:
                continue
            ma = CandidateMedal(str(a.get("candidate_medal") or "WOOD"))
            mb = CandidateMedal(str(b.get("candidate_medal") or "WOOD"))
            if _MEDAL_RANK[ma] < _MEDAL_RANK[mb]:
                if a.get("hard_cap") or b.get("hard_cap"):
                    continue
                issues.append(
                    {
                        "higher": a.get("category_code"),
                        "lower": b.get("category_code"),
                        "score_high": sa,
                        "score_low": sb,
                        "medal_high": ma.value,
                        "medal_low": mb.value,
                    }
                )
    return issues
