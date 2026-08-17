"""Track-specific Candidate Medal computation.

Medal is evaluated WITHIN opportunity_track.
Procurement total alone cannot cause GOLD.

Candidate Medal remains PRE-DOCUMENT and deterministic.
Deadline pressure may affect ranking soft-boost only — never Gold threshold.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.domain.commercial_routing_v3 import (
    CandidateMedal,
    CategoryValueBasis,
    OpportunityTrack,
    ProcurementForm,
)

CANDIDATE_MEDAL_INPUT_CONTRACT = (
    "validated semantic model result + commercial opportunity + opportunity_track "
    "+ source/lifecycle context + timing/deadline_pressure(soft) + configured business rules; "
    "scope = procurement+category+subcategory+opportunity_track; "
    "total contract value alone does NOT determine GOLD; "
    "deadline_pressure must not overpower commercial relevance; "
    "Gold threshold unchanged by urgency"
)
CANDIDATE_SCORE_COMPONENTS = (
    "commercial_relevance",
    "track_strength",
    "source_context_strength",
    "timing_deadline_pressure",
)


@dataclass(frozen=True)
class TrackMedalInput:
    opportunity_track: OpportunityTrack
    procurement_form: ProcurementForm
    category_confidence: float
    evidence_strength: float  # 0-100 non-price signals
    entry_feasibility: float  # 0-100
    value_clarity: float  # 0-100 — category-specific value clarity
    procurement_total: float = 0.0
    has_direct_value_basis: bool = False
    has_non_price_evidence: bool = False


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def compute_track_medal(inp: TrackMedalInput) -> tuple[CandidateMedal, int, int]:
    """Return (candidate_medal, commercial_priority_score, research_value_score)."""
    track = inp.opportunity_track
    conf = _clamp(inp.category_confidence * 100)
    evidence = _clamp(inp.evidence_strength)
    feasibility = _clamp(inp.entry_feasibility)
    clarity = _clamp(inp.value_clarity)

    if track == OpportunityTrack.DIRECT_SUPPLY:
        commercial = int(conf * 0.35 + clarity * 0.35 + evidence * 0.2 + feasibility * 0.1)
        research = int(conf * 0.3 + evidence * 0.4 + feasibility * 0.3)
        composite = commercial
        price_only = (
            inp.has_direct_value_basis
            and not inp.has_non_price_evidence
            and evidence < 30
        )
    elif track == OpportunityTrack.EMBEDDED_MATERIAL:
        commercial = int(evidence * 0.4 + feasibility * 0.3 + conf * 0.2 + clarity * 0.1)
        research = int(evidence * 0.35 + feasibility * 0.35 + conf * 0.3)
        composite = commercial
        price_only = not inp.has_non_price_evidence and clarity > 50 and evidence < 25
    elif track in (OpportunityTrack.DESIGN_REQUIREMENT, OpportunityTrack.DESIGN_INFLUENCE):
        weight = 1.0 if track == OpportunityTrack.DESIGN_REQUIREMENT else 0.85
        commercial = int((evidence * 0.45 + feasibility * 0.35 + conf * 0.2) * weight)
        research = int((evidence * 0.4 + feasibility * 0.4 + conf * 0.2) * weight)
        composite = research
        price_only = clarity > 40 and evidence < 20
    else:
        commercial = int(conf * 0.5)
        research = int(conf * 0.5)
        composite = max(commercial, research)
        price_only = False

    if price_only:
        composite = min(composite, 74)

    if composite >= 75:
        medal = CandidateMedal.GOLD
    elif composite >= 50:
        medal = CandidateMedal.SILVER
    elif composite >= 25:
        medal = CandidateMedal.BRONZE
    else:
        medal = CandidateMedal.WOOD

    return medal, commercial, research


def candidate_score_breakdown(
    *,
    commercial_priority_score: int,
    research_value_score: int,
    deadline_pressure: Optional[float] = None,
    commercial_timing_value: Optional[float] = None,
    source_context_strength: float = 50.0,
) -> Dict[str, Any]:
    """Visible Candidate score components. Soft timing boost only (≤15 pts).

    Uses commercial_timing_value (practical window), NOT deadline_pressure.
    Near-expiry urgency must not inflate Gold.
    """
    timing = 0.0
    if commercial_timing_value is not None:
        timing = max(0.0, min(15.0, float(commercial_timing_value) * 0.15))
    commercial = float(commercial_priority_score)
    track = float(research_value_score)
    source_ctx = float(source_context_strength)
    total = commercial + 0.25 * track + 0.10 * source_ctx + timing
    return {
        "candidate_score": round(total, 4),
        "candidate_reasons": {
            "commercial_relevance": commercial,
            "track_strength": track,
            "source_context_strength": source_ctx,
            "timing_commercial_window": round(timing, 4),
        },
        "deadline_pressure_input": deadline_pressure,
        "commercial_timing_value_input": commercial_timing_value,
        "gold_threshold_unchanged": True,
        "CANDIDATE_MEDAL_INPUT_CONTRACT": CANDIDATE_MEDAL_INPUT_CONTRACT,
    }


def resolve_category_value_basis(
    *,
    opportunity_track: OpportunityTrack,
    procurement_form: ProcurementForm,
    procurement_total: float,
    category_confidence: float,
) -> tuple[Optional[float], CategoryValueBasis]:
    if (
        opportunity_track == OpportunityTrack.DIRECT_SUPPLY
        and procurement_form == ProcurementForm.DIRECT_GOODS_PURCHASE
        and category_confidence >= 0.6
        and procurement_total > 0
    ):
        return procurement_total, CategoryValueBasis.DIRECT_PROCUREMENT_VALUE

    if opportunity_track in (
        OpportunityTrack.DESIGN_REQUIREMENT,
        OpportunityTrack.DESIGN_INFLUENCE,
    ):
        return None, CategoryValueBasis.FUTURE_REQUIREMENT

    return None, CategoryValueBasis.UNKNOWN_ADDRESSABLE_VALUE
