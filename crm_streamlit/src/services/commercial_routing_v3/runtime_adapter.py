from __future__ import annotations

from typing import Any, Dict, List

from src.domain.commercial_routing_v3 import OpportunityTrack, ResearchAction
from src.domain.commercial_routing_v3 import CategoryValueBasis


_TRACK_TO_EXPECTED_ROLE: Dict[OpportunityTrack, str] = {
    OpportunityTrack.DIRECT_SUPPLY: "PRIMARY_SUPPLY",
    OpportunityTrack.EMBEDDED_MATERIAL: "EMBEDDED_MATERIAL",
    OpportunityTrack.DESIGN_REQUIREMENT: "OBJECT_OF_RESEARCH",
    OpportunityTrack.DESIGN_INFLUENCE: "OBJECT_OF_RESEARCH",
    OpportunityTrack.NO_COMMERCIAL_ENTRY: "ABSENT",
    OpportunityTrack.UNKNOWN: "UNKNOWN",
}


_TRACK_TO_COMMERCIAL_ENTRY_POINT: Dict[OpportunityTrack, str] = {
    OpportunityTrack.DIRECT_SUPPLY: "DIRECT_SUPPLY",
    OpportunityTrack.EMBEDDED_MATERIAL: "EMBEDDED_MATERIAL",
    OpportunityTrack.DESIGN_REQUIREMENT: "DESIGN_REQUIREMENT",
    OpportunityTrack.DESIGN_INFLUENCE: "DESIGN_INFLUENCE",
    OpportunityTrack.NO_COMMERCIAL_ENTRY: "NO_COMMERCIAL_ENTRY",
    OpportunityTrack.UNKNOWN: "UNKNOWN",
}


def hypotheses_to_category_opportunities(
    *,
    hypotheses: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Convert V3 hypotheses into legacy `category_opportunities` shape
    understood by CandidatePolicy + S13_V2QueueProducer.

    This adapter does NOT compute medals; it only maps already computed
    V3 candidate fields to legacy names.
    """
    out: List[Dict[str, Any]] = []

    for h in hypotheses or []:
        # Support both dataclass-like V3 hypotheses and plain dicts.
        if not isinstance(h, dict):
            # Import locally to avoid hard coupling.
            h = {
                "commercial_category_code": getattr(h, "commercial_category_code", None),
                "commercial_subcategory_code": getattr(h, "commercial_subcategory_code", None),
                "opportunity_track": getattr(getattr(h, "opportunity_track", None), "value", None)
                or getattr(h, "opportunity_track", None),
                "category_confidence": getattr(h, "category_confidence", None),
                "research_action": getattr(getattr(h, "research_action", None), "value", None)
                or getattr(h, "research_action", None),
                "research_priority": getattr(h, "research_priority", None),
                "commercial_priority_score": getattr(h, "commercial_priority_score", None),
                "research_value_score": getattr(h, "research_value_score", None),
                "candidate_medal": getattr(getattr(h, "candidate_medal", None), "value", None)
                or getattr(h, "candidate_medal", None),
                "expected_category_value": getattr(h, "expected_category_value", None),
                "category_value_basis": getattr(getattr(h, "category_value_basis", None), "value", None)
                or getattr(h, "category_value_basis", None),
                "reason_codes": getattr(h, "reason_codes", None) or [],
                "positive_evidence": getattr(h, "positive_evidence", None) or [],
                "negative_evidence": getattr(h, "negative_evidence", None) or [],
            }

        track_raw = h.get("opportunity_track") or OpportunityTrack.UNKNOWN.value
        try:
            track = OpportunityTrack(track_raw)
        except Exception:
            track = OpportunityTrack.UNKNOWN

        confidence = float(h.get("category_confidence") or h.get("confidence") or 0.0)

        research_action_raw = h.get("research_action") or ResearchAction.LIGHT_RESEARCH.value
        try:
            research_action = ResearchAction(research_action_raw).value
        except Exception:
            research_action = str(research_action_raw).upper()

        expected_role = _TRACK_TO_EXPECTED_ROLE.get(track, "UNKNOWN")
        commercial_entry_point = _TRACK_TO_COMMERCIAL_ENTRY_POINT.get(track, "UNKNOWN")

        # V3 candidate medal/score are track-specific; keep them untouched.
        candidate_level = h.get("candidate_medal") or h.get("candidate_level") or None
        candidate_score = (
            h.get("candidate_score")
            or h.get("final_score")
            or h.get("commercial_priority_score")
            or h.get("research_value_score")
        )

        # OLD opp_status semantics: CONFIRMED_SOURCE vs POSSIBLE.
        opp_status = "CONFIRMED_SOURCE" if confidence >= 0.7 else "POSSIBLE"

        out.append(
            {
                "category_code": h.get("commercial_category_code"),
                "subcategory_code": h.get("commercial_subcategory_code"),
                "opportunity_track": track.value,
                "opportunity_status": opp_status,
                "expected_role": expected_role,
                "commercial_entry_point": commercial_entry_point,
                # Legacy volume is used by CandidatePolicy only when it recomputes;
                # V3 integration guard reuses precomputed medal/score.
                "expected_volume": "UNKNOWN",
                "confidence": confidence,
                "priority": float(h.get("research_priority") or 1.0),
                "research_action": research_action,
                "research_value_score": h.get("research_value_score"),
                "commercial_priority_score": h.get("commercial_priority_score"),
                "candidate_medal": candidate_level,
                "candidate_level": candidate_level,
                "candidate_score": float(candidate_score) if candidate_score is not None else None,
                "expected_category_value": h.get("expected_category_value"),
                "reason_codes": h.get("reason_codes") or [],
                "positive_evidence": h.get("positive_evidence") or [],
                "negative_evidence": h.get("negative_evidence") or [],
                "category_value_basis": h.get("category_value_basis"),
            }
        )

    # Deterministic order: higher score first
    out.sort(key=lambda x: float(x.get("candidate_score") or 0.0), reverse=True)
    return out


def decision_to_normalized_result(
    *,
    decision: Any,
    procurement: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create runtime `normalized_result` dict shape that downstream
    CandidatePolicy + S13V2QueueProducer understand.
    """
    def _get(dec: Any, key: str, default: Any = None) -> Any:
        if hasattr(dec, key):
            return getattr(dec, key)
        if isinstance(dec, dict):
            return dec.get(key, default)
        return default

    hypotheses = _get(decision, "commercial_category_hypotheses", None)
    discovery_required = bool(_get(decision, "discovery_required", False))
    overall_research_action = _get(decision, "overall_research_action", None)
    if overall_research_action:
        overall_research_action = str(overall_research_action).upper()

    # CandidatePolicy works off this legacy key.
    category_opportunities = hypotheses_to_category_opportunities(hypotheses=hypotheses)

    # Preserve canonical V3 hypotheses (compatibility layer must not drop semantics).
    commercial_category_hypotheses: List[Dict[str, Any]] = []
    if hasattr(decision, "to_normalized_dict"):
        try:
            commercial_category_hypotheses = (
                decision.to_normalized_dict().get("commercial_category_hypotheses") or []
            )
        except Exception:
            commercial_category_hypotheses = []
    elif isinstance(decision, dict):
        commercial_category_hypotheses = decision.get("commercial_category_hypotheses") or []
    details = list(_get(decision, "hypothesis_details", None) or [])
    if details:
        commercial_category_hypotheses = details
    if not commercial_category_hypotheses and hypotheses:
        commercial_category_hypotheses = [
            {
                "category_code": h.get("commercial_category_code") if isinstance(h, dict) else getattr(h, "commercial_category_code", None),
                "subcategory_code": h.get("commercial_subcategory_code") if isinstance(h, dict) else getattr(h, "commercial_subcategory_code", None),
                "opportunity_track": (h.get("opportunity_track") if isinstance(h, dict) else getattr(getattr(h, "opportunity_track", None), "value", None)),
                "confidence": h.get("category_confidence") if isinstance(h, dict) else getattr(h, "category_confidence", None),
                "research_action": h.get("research_action") if isinstance(h, dict) else getattr(getattr(h, "research_action", None), "value", None),
                "commercial_priority_score": h.get("commercial_priority_score") if isinstance(h, dict) else getattr(h, "commercial_priority_score", None),
                "research_value_score": h.get("research_value_score") if isinstance(h, dict) else getattr(h, "research_value_score", None),
                "candidate_medal": h.get("candidate_medal") if isinstance(h, dict) else getattr(getattr(h, "candidate_medal", None), "value", None),
                "reason_codes": h.get("reason_codes") if isinstance(h, dict) else getattr(h, "reason_codes", None),
                "negative_evidence": h.get("negative_evidence") if isinstance(h, dict) else getattr(h, "negative_evidence", None),
            }
            for h in (hypotheses or [])
        ]

    sc = _get(decision, "source_contour", None)
    pf = _get(decision, "procurement_form", None)
    am = _get(decision, "analysis_modes", None)
    am0 = am[0] if am else None
    rv = _get(decision, "registry_version", None)
    rh = _get(decision, "registry_hash", None)
    pv = _get(decision, "prompt_version", None)
    rvn = _get(decision, "routing_version", None)
    mn = _get(decision, "model_name", None)

    def _enum_value(x: Any) -> Any:
        return x.value if hasattr(x, "value") else x

    return {
        # Procurement-level V3 keys for queue producer policy.
        "discovery_required": discovery_required,
        "overall_research_action": overall_research_action,
        "empty_hypothesis_status": _get(decision, "empty_hypothesis_status", None),
        "empty_hypothesis_reason_codes": list(
            _get(decision, "empty_hypothesis_reason_codes", None) or []
        ),
        "rejected_category_codes": list(_get(decision, "rejected_category_codes", None) or []),
        "preferred_opportunity_track": _get(decision, "preferred_opportunity_track", None),
        "review_required": bool(_get(decision, "review_required", False)),
        # Runtime contract for persistence/lifecycle sync.
        "source_contour": _enum_value(sc),
        "procurement_form": _enum_value(pf),
        "analysis_mode": _enum_value(am0),
        "analysis_modes": [_enum_value(m) for m in (am or [])],
        "object_context": list(_get(decision, "object_context", None) or []),
        "material_signals": list(_get(decision, "material_signals", None) or []),
        "work_methods": list(_get(decision, "work_methods", None) or []),
        "application_areas": list(_get(decision, "application_areas", None) or []),
        "brands": list(_get(decision, "brands", None) or []),
        "commercial_category_hypotheses": commercial_category_hypotheses,
        "routing_mode": _get(decision, "routing_mode", None),
        "object_classification": _get(decision, "object_classification", None),
        "document_research_priority": list(_get(decision, "document_research_priority", None) or []),
        "hypothesis_details": list(_get(decision, "hypothesis_details", None) or []),
        "awarded_context": _get(decision, "awarded_context", None),
        "post_award_commercial_target": _get(decision, "post_award_commercial_target", None),
        "post_award_commercial_target_name": _get(
            decision, "post_award_commercial_target_name", None
        ),
        "registry_version": rv or 1,
        "registry_hash": rh or "",
        "prompt_version": pv or "",
        "routing_version": rvn or "v3",
        "model_name": mn or "",
        # Legacy keys expected by existing pipeline.
        "business_scope_status": "IN_PROFILE",
        "route_profile": "UNASSESSED",
        "category_opportunities": category_opportunities,
    }

