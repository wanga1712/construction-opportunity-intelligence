"""Strict MODEL validation boundary (Phase 6A).

MODEL_VALIDATED may only:
- parse already-parsed JSON shape checks
- canonicalize approved enum aliases / spelling / case
- normalize trivial primitive types
- reject invalid fields

It must NOT invent commercial hypotheses, scope, confidence, score, or medal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from src.domain.commercial_routing_v3 import (
    AnalysisMode,
    OpportunityTrack,
    ProcurementForm,
    ResearchAction,
    SourceContour,
)
from src.services.commercial_routing_v3.category_aliases import resolve_explicit_category_alias
from src.services.commercial_routing_v3.candidate_scoring import looks_like_okpd_category_code
from src.domain.commercial_taxonomy import is_valid_commercial_category_code

SCHEMA_VERSION_MODEL_VALIDATED = "v3_model_validated_1"

_VALID_FORMS = {f.value for f in ProcurementForm}
_VALID_MODES = {m.value for m in AnalysisMode}
_VALID_TRACKS = {t.value for t in OpportunityTrack}
_VALID_ACTIONS = {a.value for a in ResearchAction}
_VALID_CONTOURS = {c.value for c in SourceContour}
_VALID_EMPTY = {
    "NO_COMMERCIAL_ENTRY",
    "INSUFFICIENT_EVIDENCE",
    "REVIEW_REQUIRED",
}
_SUB_SENTINEL = "SUBCATEGORY_NOT_ASSIGNED"

_ALLOWED_TOP_KEYS = frozenset(
    {
        "source_contour",
        "procurement_form",
        "analysis_modes",
        "analysis_mode",
        "object_context",
        "material_signals",
        "work_methods",
        "application_areas",
        "brands",
        "commercial_category_hypotheses",
        "commercial_category_candidates",  # Phase 9 SHADOW alias → normalized to hyps
        "subject_interpretation",  # Phase 9 semantic subject (MODEL, not business)
        "empty_hypothesis_status",
        "preferred_opportunity_track",
        "empty_hypothesis_reason_codes",
        "discovery_required",
        "overall_research_action",
        "object_classification",
        "document_research_priority",
        "review_required",
    }
)

_VALID_RESEARCH_PRIORITY = frozenset({"HIGH", "MEDIUM", "LOW"})
_VALID_CANDIDATE_ROLE = frozenset(
    {"DIRECT_PURCHASE", "RESEARCH_CANDIDATE", "DIRECT_SUPPLY", "EMBEDDED_MATERIAL"}
)


@dataclass
class ModelValidationResult:
    status: str  # VALIDATED_SUCCESS | PARSED_SCHEMA_INVALID
    validated: Optional[Dict[str, Any]] = None
    errors: List[str] = field(default_factory=list)


def _as_float_or_none(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _canonicalize_enum(raw: Any, allowed: Set[str], *, default: Optional[str] = None) -> Optional[str]:
    if raw is None:
        return default
    s = str(raw).strip()
    if not s:
        return default
    if s in allowed:
        return s
    up = s.upper()
    for a in allowed:
        if a.upper() == up:
            return a
    return None


def _normalize_phase9_candidates(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Map commercial_category_candidates → hypotheses without inventing codes.

    Keeps subject_interpretation intact. Does not invent empty_hypothesis_status.
    """
    out = dict(parsed)
    cands = out.get("commercial_category_candidates")
    hyps = out.get("commercial_category_hypotheses")
    if isinstance(cands, list) and cands and (not hyps):
        mapped: List[Dict[str, Any]] = []
        for c in cands[:5]:
            if not isinstance(c, dict):
                continue
            role = str(c.get("candidate_role") or "").strip().upper()
            track = c.get("opportunity_track")
            if not track:
                if role in {"DIRECT_PURCHASE", "DIRECT_SUPPLY"}:
                    track = "DIRECT_SUPPLY"
                elif role in {"RESEARCH_CANDIDATE", "EMBEDDED_MATERIAL"}:
                    track = "EMBEDDED_MATERIAL"
            evid = c.get("evidence_role")
            if not evid:
                evid = (
                    "DIRECT_CATEGORY_EVIDENCE"
                    if role in {"DIRECT_PURCHASE", "DIRECT_SUPPLY"}
                    else "CONTEXTUAL_RESEARCH_CANDIDATE"
                )
            conf_req = c.get("confirmation_required")
            if conf_req is None:
                conf_req = role in {"RESEARCH_CANDIDATE", "EMBEDDED_MATERIAL"}
            mapped.append(
                {
                    "category_code": c.get("category_code") or c.get("commercial_category_code"),
                    "subcategory_code": c.get("subcategory_code") or "SUBCATEGORY_NOT_ASSIGNED",
                    "opportunity_track": track,
                    "confidence": c.get("confidence"),
                    "research_action": c.get("research_action") or "LIGHT_RESEARCH",
                    "reason_codes": c.get("reason_codes") or [],
                    "evidence_role": evid,
                    "confirmation_required": bool(conf_req),
                    "research_priority": c.get("research_priority"),
                    "candidate_role": c.get("candidate_role"),
                }
            )
        out["commercial_category_hypotheses"] = mapped
    return out


def validate_model_result(
    parsed: Optional[Dict[str, Any]],
    *,
    allowed_categories: Set[str],
    allowed_subcategories: Optional[Dict[str, Set[str]]] = None,
) -> ModelValidationResult:
    """Schema/type/enum-only interpretation of MODEL_RAW parse output."""
    errors: List[str] = []
    if not isinstance(parsed, dict):
        return ModelValidationResult(
            status="PARSED_SCHEMA_INVALID",
            validated=None,
            errors=["parsed_not_object"],
        )

    parsed = _normalize_phase9_candidates(parsed)

    # Drop unknown/telemetry keys — never invent business fields.
    out: Dict[str, Any] = {}
    for k, v in parsed.items():
        if str(k).startswith("_"):
            errors.append(f"rejected_telemetry_key:{k}")
            continue
        if k not in _ALLOWED_TOP_KEYS:
            # Keep unknown model keys only if they are not telemetry; still reject
            # known business-invented namespaces.
            if k in {
                "business_scope_status",
                "candidate_score",
                "candidate_medal",
                "candidate_level",
                "category_opportunities",
            }:
                errors.append(f"rejected_business_field:{k}")
                continue
            # Unknown keys rejected from validated namespace (strict).
            errors.append(f"rejected_unknown_key:{k}")
            continue
        out[k] = v

    contour = _canonicalize_enum(out.get("source_contour"), _VALID_CONTOURS, default=SourceContour.UNKNOWN.value)
    if out.get("source_contour") is not None and contour is None:
        errors.append("invalid_source_contour")
        contour = SourceContour.UNKNOWN.value
    out["source_contour"] = contour

    form = _canonicalize_enum(out.get("procurement_form"), _VALID_FORMS, default=ProcurementForm.UNKNOWN.value)
    if out.get("procurement_form") is not None and form is None:
        errors.append("invalid_procurement_form")
        form = ProcurementForm.UNKNOWN.value
    out["procurement_form"] = form

    modes = out.get("analysis_modes") or out.get("analysis_mode")
    if isinstance(modes, str):
        modes = [modes]
    clean_modes: List[str] = []
    for m in modes or []:
        cm = _canonicalize_enum(m, _VALID_MODES)
        if cm:
            clean_modes.append(cm)
        else:
            errors.append(f"invalid_analysis_mode:{m}")
    out["analysis_modes"] = clean_modes
    out.pop("analysis_mode", None)

    for key in ("material_signals", "work_methods", "application_areas", "brands", "object_context"):
        vals = out.get(key)
        if vals is None:
            out[key] = []
        elif isinstance(vals, list):
            out[key] = [str(x) for x in vals[:8]]
        else:
            errors.append(f"invalid_list:{key}")
            out[key] = []

    subs = allowed_subcategories or {}
    hyps_in = out.get("commercial_category_hypotheses")
    hyps_out: List[Dict[str, Any]] = []
    if hyps_in is None:
        out["commercial_category_hypotheses"] = []
    elif not isinstance(hyps_in, list):
        errors.append("commercial_category_hypotheses_not_list")
        out["commercial_category_hypotheses"] = []
    else:
        for h in hyps_in[:5]:
            if not isinstance(h, dict):
                errors.append("hypothesis_not_object")
                continue
            raw_cat = h.get("category_code") or h.get("commercial_category_code") or ""
            raw_cat_s = str(raw_cat).strip() if raw_cat is not None else ""
            if not raw_cat_s:
                errors.append("hypothesis_missing_category")
                continue
            alias = resolve_explicit_category_alias(raw_cat_s, allowed_categories=allowed_categories)
            if alias:
                cat = alias
            elif looks_like_okpd_category_code(raw_cat_s):
                errors.append(f"rejected_okpd_as_category:{raw_cat_s}")
                continue
            elif not is_valid_commercial_category_code(raw_cat_s):
                errors.append(f"rejected_invalid_category_format:{raw_cat_s}")
                continue
            elif raw_cat_s not in allowed_categories:
                errors.append(f"rejected_category_not_in_registry:{raw_cat_s}")
                continue
            else:
                cat = raw_cat_s

            sub = h.get("subcategory_code") or h.get("commercial_subcategory_code")
            if sub == _SUB_SENTINEL:
                sub = None
            elif sub and str(sub) not in subs.get(cat, set()):
                # Drop invalid subcategory; do not invent a replacement.
                errors.append(f"dropped_invalid_subcategory:{sub}")
                sub = None

            track = _canonicalize_enum(h.get("opportunity_track"), _VALID_TRACKS, default=OpportunityTrack.UNKNOWN.value)
            if h.get("opportunity_track") is not None and track is None:
                errors.append(f"invalid_opportunity_track:{h.get('opportunity_track')}")
                track = OpportunityTrack.UNKNOWN.value

            action = _canonicalize_enum(
                h.get("research_action"), _VALID_ACTIONS, default=ResearchAction.SKIP.value
            )
            if h.get("research_action") is not None and action is None:
                errors.append(f"invalid_research_action:{h.get('research_action')}")
                action = ResearchAction.SKIP.value

            conf = _as_float_or_none(h.get("confidence"))
            if conf is None:
                conf = _as_float_or_none(h.get("category_confidence"))
            # Preserve explicit 0.0; missing stays None (not invented).

            rp_raw = h.get("research_priority")
            rp = None
            if rp_raw is not None and str(rp_raw).strip():
                rp_s = str(rp_raw).strip().upper()
                if rp_s in _VALID_RESEARCH_PRIORITY:
                    rp = rp_s
                else:
                    errors.append(f"invalid_research_priority:{rp_raw}")

            role_raw = h.get("candidate_role")
            role = None
            if role_raw is not None and str(role_raw).strip():
                role_s = str(role_raw).strip().upper()
                if role_s in _VALID_CANDIDATE_ROLE:
                    role = role_s
                else:
                    errors.append(f"invalid_candidate_role:{role_raw}")

            row = {
                "category_code": cat,
                "model_raw_category_code": raw_cat_s,
                "subcategory_code": sub,
                "opportunity_track": track,
                "confidence": conf,
                "research_action": action,
                "reason_codes": [str(c) for c in (h.get("reason_codes") or [])][:6],
                "positive_evidence": list(h.get("positive_evidence") or [])[:8],
                "negative_evidence": list(h.get("negative_evidence") or [])[:8],
                "evidence_role": h.get("evidence_role"),
                "confirmation_required": h.get("confirmation_required"),
                "why_category": h.get("why_category"),
                "research_priority": rp,
                "candidate_role": role,
                # Explicitly no score/medal invention.
                "candidate_medal": None,
                "candidate_score": None,
                "commercial_priority_score": None,
                "research_value_score": None,
            }
            hyps_out.append(row)
        out["commercial_category_hypotheses"] = hyps_out

    # Preserve Phase 9 subject interpretation (semantic MODEL field only).
    subj = out.get("subject_interpretation")
    if subj is None:
        pass
    elif not isinstance(subj, dict):
        errors.append("subject_interpretation_not_object")
        out.pop("subject_interpretation", None)
    else:
        clean_subj: Dict[str, Any] = {}
        for sk in (
            "subject_type",
            "normalized_subject",
            "object_type",
            "work_stage",
            "object_subtype",
        ):
            if subj.get(sk) is not None and str(subj.get(sk)).strip():
                clean_subj[sk] = str(subj.get(sk)).strip()[:240]
        out["subject_interpretation"] = clean_subj

    cands_in = out.get("commercial_category_candidates")
    if cands_in is None:
        pass
    elif not isinstance(cands_in, list):
        errors.append("commercial_category_candidates_not_list")
        out["commercial_category_candidates"] = []
    else:
        valid_codes = {h["category_code"] for h in out.get("commercial_category_hypotheses") or []}
        kept = []
        for c in cands_in[:5]:
            if not isinstance(c, dict):
                continue
            cc = str(c.get("category_code") or "").strip()
            if cc in valid_codes:
                kept.append(
                    {
                        "category_code": cc,
                        "candidate_role": c.get("candidate_role"),
                        "research_priority": c.get("research_priority"),
                        "confirmation_required": c.get("confirmation_required"),
                        "evidence_role": c.get("evidence_role"),
                    }
                )
        out["commercial_category_candidates"] = kept

    empty = out.get("empty_hypothesis_status")
    if empty is None or empty == "":
        out["empty_hypothesis_status"] = None
    else:
        empty_s = str(empty).strip().upper()
        if empty_s not in _VALID_EMPTY:
            errors.append(f"invalid_empty_hypothesis_status:{empty}")
            out["empty_hypothesis_status"] = None
        else:
            out["empty_hypothesis_status"] = empty_s

    pref = out.get("preferred_opportunity_track")
    if pref is None or pref == "":
        out["preferred_opportunity_track"] = None
    else:
        pref_c = _canonicalize_enum(pref, _VALID_TRACKS)
        if pref_c is None:
            errors.append(f"invalid_preferred_opportunity_track:{pref}")
            out["preferred_opportunity_track"] = None
        else:
            out["preferred_opportunity_track"] = pref_c

    out["empty_hypothesis_reason_codes"] = [
        str(c) for c in (out.get("empty_hypothesis_reason_codes") or [])
    ][:6]

    overall = out.get("overall_research_action")
    if overall is None or overall == "":
        out["overall_research_action"] = None
    else:
        ov = _canonicalize_enum(overall, _VALID_ACTIONS)
        if ov is None:
            errors.append(f"invalid_overall_research_action:{overall}")
            out["overall_research_action"] = None
        else:
            out["overall_research_action"] = ov

    if "discovery_required" in out:
        out["discovery_required"] = bool(out.get("discovery_required"))
    if "review_required" in out:
        out["review_required"] = bool(out.get("review_required"))

    oc = out.get("object_classification")
    if oc is not None and not isinstance(oc, dict):
        errors.append("object_classification_not_object")
        out.pop("object_classification", None)

    drp = out.get("document_research_priority")
    if drp is not None and not isinstance(drp, list):
        errors.append("document_research_priority_not_list")
        out["document_research_priority"] = []

    # Never invent commercial hypotheses / scope / confidence / medals.
    if "business_scope_status" in out:
        out.pop("business_scope_status", None)
        errors.append("rejected_business_scope_status")

    # Schema-invalid only when core object shape is unusable.
    fatal = any(
        e.startswith("parsed_not_object")
        or e.startswith("commercial_category_hypotheses_not_list")
        for e in errors
    )
    if fatal:
        return ModelValidationResult(status="PARSED_SCHEMA_INVALID", validated=None, errors=errors)

    out["schema_version"] = SCHEMA_VERSION_MODEL_VALIDATED
    return ModelValidationResult(status="VALIDATED_SUCCESS", validated=out, errors=errors)
