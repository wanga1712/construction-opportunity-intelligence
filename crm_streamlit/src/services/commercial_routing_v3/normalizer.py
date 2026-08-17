"""Deterministic normalization and validation for V3 AI output."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from src.domain.commercial_routing_v3 import (
    AnalysisMode,
    CandidateMedal,
    CategoryValueBasis,
    OpportunityTrack,
    ProcurementForm,
    ResearchAction,
    SourceContour,
    TRACKS_FOR_FORM,
)
from src.services.commercial_routing_v3.category_aliases import resolve_explicit_category_alias
from src.services.commercial_routing_v3.candidate_scoring import looks_like_okpd_category_code
from src.domain.commercial_taxonomy import is_valid_commercial_category_code


_VALID_FORMS = {f.value for f in ProcurementForm}
_VALID_MODES = {m.value for m in AnalysisMode}
_VALID_TRACKS = {t.value for t in OpportunityTrack}
_VALID_ACTIONS = {a.value for a in ResearchAction}
_VALID_MEDALS = {m.value for m in CandidateMedal}
_VALID_CONTOURS = {c.value for c in SourceContour}
_VALID_BASES = {b.value for b in CategoryValueBasis}
_VALID_EMPTY_STATUS = {
    "NO_COMMERCIAL_ENTRY",
    "INSUFFICIENT_EVIDENCE",
    "REVIEW_REQUIRED",
}
_SUB_SENTINEL = "SUBCATEGORY_NOT_ASSIGNED"

# Non-category dimensions / forms that must never pass as commercial_category
_NONCATEGORY_CODES = frozenset(
    {
        # procurement forms (snake + enum values lower)
        "survey_and_design",
        "design_only",
        "design_and_build",
        "design_expertise_and_build",
        "construction_works",
        "direct_goods_purchase",
        "works_other",
        "services_other",
        # dimension-ish
        "material_family",
        "work_method",
        "application_area",
        "object_context",
        "brand",
        "manufacturer",
        "model",
    }
) | {f.value.lower() for f in ProcurementForm}


def _normalize_raw_category(
    raw: str,
    *,
    allowed_categories: Set[str],
) -> tuple[str, Optional[str]]:
    """Return (canonical_code, rejection_reason). Empty code → ('', reason)."""
    cat = str(raw or "").strip()
    if not cat:
        return "", "empty"
    alias = resolve_explicit_category_alias(cat, allowed_categories=allowed_categories)
    if alias:
        return alias, None
    if looks_like_okpd_category_code(cat):
        return "", "okpd_not_category"
    low = cat.strip().lower()
    if low in _NONCATEGORY_CODES:
        return "", "noncategory_dimension"
    if not is_valid_commercial_category_code(cat):
        return "", "invalid_format"
    if cat not in allowed_categories:
        return "", "not_in_registry"
    return cat, None


def _coerce_track_for_form(form: str, track: str) -> str:
    """Runtime contract: form forbids DIRECT_SUPPLY for construction/design."""
    try:
        form_enum = ProcurementForm(form)
    except ValueError:
        return track
    allowed = TRACKS_FOR_FORM.get(form_enum)
    if not allowed:
        return track
    allowed_vals = {t.value for t in allowed}
    if track in allowed_vals:
        return track
    if track == OpportunityTrack.DIRECT_SUPPLY.value:
        if form_enum == ProcurementForm.CONSTRUCTION_WORKS:
            return OpportunityTrack.EMBEDDED_MATERIAL.value
        if form_enum in (
            ProcurementForm.DESIGN_ONLY,
            ProcurementForm.SURVEY_AND_DESIGN,
            ProcurementForm.DESIGN_AND_BUILD,
            ProcurementForm.DESIGN_EXPERTISE_AND_BUILD,
        ):
            return OpportunityTrack.DESIGN_REQUIREMENT.value
    return allowed[0].value


def _is_rejected_category(cat: str, allowed_categories: Set[str]) -> bool:
    canonical, reason = _normalize_raw_category(cat, allowed_categories=allowed_categories)
    return reason is not None or not canonical


def _hyp_confidence(h: Dict[str, Any]) -> float:
    raw = h.get("confidence")
    if raw is None:
        raw = h.get("category_confidence")
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def _unambiguous_rejected_nce(
    raw_hyps: List[Dict[str, Any]],
    *,
    allowed_categories: Set[str],
    kept: List[Dict[str, Any]],
    rejected: List[str],
) -> bool:
    """Recover NCE only when every raw hyp is a non-registry code with NCE track.

    Narrow: any commercial claim (other track, confidence>0, positive evidence,
    mix of valid+invalid) stays REVIEW_REQUIRED.
    """
    if kept or not rejected:
        return False
    if not raw_hyps:
        return False
    for h in raw_hyps[:3]:
        if not isinstance(h, dict):
            return False
        cat = str(h.get("category_code") or h.get("commercial_category_code") or "").strip()
        if not cat or not _is_rejected_category(cat, allowed_categories):
            return False
        track = str(h.get("opportunity_track") or "").strip().upper()
        if track != OpportunityTrack.NO_COMMERCIAL_ENTRY.value:
            return False
        if _hyp_confidence(h) > 0:
            return False
        if h.get("positive_evidence"):
            return False
    return True


def _apply_nce_empty(out: Dict[str, Any], *, extra_reasons: List[str] | None = None) -> None:
    reasons = [str(c) for c in (out.get("empty_hypothesis_reason_codes") or [])]
    if extra_reasons:
        for r in extra_reasons:
            if r not in reasons:
                reasons.append(r)
    out["commercial_category_hypotheses"] = []
    out["empty_hypothesis_status"] = "NO_COMMERCIAL_ENTRY"
    out["overall_research_action"] = ResearchAction.SKIP.value
    out["discovery_required"] = False
    out["review_required"] = False
    out["empty_hypothesis_reason_codes"] = reasons[:6]


def normalize_v3_output(
    raw: Dict[str, Any],
    *,
    allowed_categories: Set[str],
    allowed_subcategories: Dict[str, Set[str]],
    has_okpd: bool,
) -> Dict[str, Any]:
    out = dict(raw or {})

    contour = out.get("source_contour", SourceContour.UNKNOWN.value)
    out["source_contour"] = contour if contour in _VALID_CONTOURS else SourceContour.UNKNOWN.value

    form = out.get("procurement_form", ProcurementForm.UNKNOWN.value)
    out["procurement_form"] = form if form in _VALID_FORMS else ProcurementForm.UNKNOWN.value
    form = out["procurement_form"]

    modes = out.get("analysis_modes") or out.get("analysis_mode")
    if isinstance(modes, str):
        modes = [modes]
    out["analysis_modes"] = [m for m in (modes or []) if m in _VALID_MODES] or [
        AnalysisMode.GENERAL_DISCOVERY.value
    ]

    for key in ("material_signals", "work_methods", "application_areas", "brands", "object_context"):
        vals = out.get(key) or []
        if isinstance(vals, list):
            out[key] = vals[:8]
        else:
            out[key] = []

    rejected: List[str] = []
    rejection_details: List[Dict[str, str]] = []
    hypotheses: List[Dict[str, Any]] = []
    raw_hyps = [h for h in (out.get("commercial_category_hypotheses") or [])[:5] if isinstance(h, dict)]
    for h in raw_hyps:
        raw_cat = h.get("category_code") or h.get("commercial_category_code") or ""
        cat, rej_reason = _normalize_raw_category(str(raw_cat).strip(), allowed_categories=allowed_categories)
        if rej_reason or not cat:
            if raw_cat:
                rejected.append(str(raw_cat).strip())
                rejection_details.append(
                    {"raw": str(raw_cat).strip(), "reason": rej_reason or "rejected"}
                )
            continue
        sub = h.get("subcategory_code") or h.get("commercial_subcategory_code")
        if sub == _SUB_SENTINEL:
            sub = None
        elif sub and sub not in allowed_subcategories.get(cat, set()):
            sub = None
        track = h.get("opportunity_track", OpportunityTrack.UNKNOWN.value)
        if track not in _VALID_TRACKS:
            track = OpportunityTrack.UNKNOWN.value
        track = _coerce_track_for_form(form, track)
        action = h.get("research_action", ResearchAction.SKIP.value)
        if action not in _VALID_ACTIONS:
            action = ResearchAction.SKIP.value
        # Model must not set medal/score — canonical authority applies later in engine.
        basis = h.get("category_value_basis", CategoryValueBasis.UNKNOWN_ADDRESSABLE_VALUE.value)
        if basis not in _VALID_BASES:
            basis = CategoryValueBasis.UNKNOWN_ADDRESSABLE_VALUE.value
        reason_codes = [c for c in (h.get("reason_codes") or []) if c != "okpd_match" or has_okpd][:6]
        if track != (h.get("opportunity_track") or "") and "track_coerced_by_form" not in reason_codes:
            reason_codes = (reason_codes + ["track_coerced_by_form"])[:6]
        hypotheses.append(
            {
                "category_code": cat,
                "model_raw_category_code": str(raw_cat).strip() if raw_cat else None,
                "subcategory_code": sub,
                "subcategory_status": "ASSIGNED" if sub else _SUB_SENTINEL,
                "opportunity_track": track,
                "confidence": float(h.get("confidence") or h.get("category_confidence") or 0),
                "research_action": action,
                "research_priority": 0,
                "commercial_priority_score": 0,
                "research_value_score": 0,
                "candidate_medal": None,
                "expected_category_value": h.get("expected_category_value"),
                "category_value_basis": basis,
                "reason_codes": reason_codes,
                "positive_evidence": list(h.get("positive_evidence") or [])[:8],
                "negative_evidence": list(h.get("negative_evidence") or [])[:8],
                "evidence_role": h.get("evidence_role"),
                "confirmation_required": h.get("confirmation_required"),
                "why_category": h.get("why_category"),
            }
        )
    out["commercial_category_hypotheses"] = hypotheses
    out["rejected_category_codes"] = rejected[:8]
    out["category_rejection_details"] = rejection_details[:8]

    empty_status = (out.get("empty_hypothesis_status") or "").strip().upper() or None
    if empty_status and empty_status not in _VALID_EMPTY_STATUS:
        empty_status = "REVIEW_REQUIRED"
    pref_track = (out.get("preferred_opportunity_track") or "").strip().upper() or None
    if pref_track and pref_track not in _VALID_TRACKS:
        pref_track = None
    if pref_track:
        pref_track = _coerce_track_for_form(form, pref_track)

    empty_reasons = [str(c) for c in (out.get("empty_hypothesis_reason_codes") or [])][:6]

    if not hypotheses:
        if _unambiguous_rejected_nce(
            raw_hyps,
            allowed_categories=allowed_categories,
            kept=hypotheses,
            rejected=rejected,
        ):
            _apply_nce_empty(
                out,
                extra_reasons=empty_reasons
                + ["rejected_nonregistry_nce_recovered"]
                + [f"rejected:{c}" for c in rejected],
            )
            out["rejected_category_codes"] = rejected[:8]
            out["preferred_opportunity_track"] = (
                pref_track or OpportunityTrack.NO_COMMERCIAL_ENTRY.value
            )
            return out
        # Invalid / non-category emissions → REVIEW + discovery (never silent empty, never NCE)
        if rejected:
            empty_status = "REVIEW_REQUIRED"
            empty_reasons = (empty_reasons + ["invalid_category_rejected"] + [f"rejected:{c}" for c in rejected])[
                :6
            ]
            out["review_required"] = True
            out["discovery_required"] = True
            out["overall_research_action"] = ResearchAction.DISCOVER_COMMERCIAL_CATEGORY.value
            if not pref_track:
                try:
                    allowed = TRACKS_FOR_FORM.get(ProcurementForm(form)) or []
                    if allowed:
                        pref_track = allowed[0].value
                except ValueError:
                    pref_track = OpportunityTrack.UNKNOWN.value
        elif not empty_status:
            # True silent empty (no cats attempted) — still invalid, force review discovery
            empty_status = "REVIEW_REQUIRED"
            empty_reasons = empty_reasons or ["silent_empty_hypotheses"]
            out["review_required"] = True
            out["discovery_required"] = True
            out["overall_research_action"] = ResearchAction.DISCOVER_COMMERCIAL_CATEGORY.value
            if not pref_track:
                try:
                    allowed = TRACKS_FOR_FORM.get(ProcurementForm(form)) or []
                    if allowed:
                        pref_track = allowed[0].value
                except ValueError:
                    pref_track = OpportunityTrack.UNKNOWN.value
        else:
            # Explicit empty (incl. NO_COMMERCIAL_ENTRY) preserved
            out["review_required"] = empty_status in ("INSUFFICIENT_EVIDENCE", "REVIEW_REQUIRED")
            if empty_status == "REVIEW_REQUIRED":
                out["discovery_required"] = True
                if out.get("overall_research_action") not in _VALID_ACTIONS:
                    out["overall_research_action"] = ResearchAction.DISCOVER_COMMERCIAL_CATEGORY.value
            if empty_status == "NO_COMMERCIAL_ENTRY":
                out["review_required"] = False
                out["discovery_required"] = False
                out["overall_research_action"] = ResearchAction.SKIP.value
            if not pref_track:
                try:
                    allowed = TRACKS_FOR_FORM.get(ProcurementForm(form)) or []
                    if allowed:
                        pref_track = allowed[0].value
                except ValueError:
                    pref_track = OpportunityTrack.UNKNOWN.value
    else:
        out["review_required"] = bool(out.get("review_required"))
        empty_status = None

    out["empty_hypothesis_status"] = empty_status
    out["preferred_opportunity_track"] = pref_track
    out["empty_hypothesis_reason_codes"] = empty_reasons

    overall = out.get("overall_research_action", ResearchAction.SKIP.value)
    out["overall_research_action"] = overall if overall in _VALID_ACTIONS else ResearchAction.SKIP.value
    out["discovery_required"] = bool(out.get("discovery_required"))
    if out.get("empty_hypothesis_status") == "NO_COMMERCIAL_ENTRY" and not out.get(
        "commercial_category_hypotheses"
    ):
        out["overall_research_action"] = ResearchAction.SKIP.value
        out["discovery_required"] = False
        out["review_required"] = False
    return out
