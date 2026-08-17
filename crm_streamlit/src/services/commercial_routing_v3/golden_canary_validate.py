"""Validate golden canary model outputs against pre-declared reference expectations."""
from __future__ import annotations

from typing import Any, Dict, List, Set

from src.domain.commercial_taxonomy import is_valid_commercial_category_code
from src.services.commercial_routing_v3.golden_canary_select import ReferenceExpectation

# brand/method/area alone must not invent commercial category
_FORBIDDEN_CATEGORY_SHORTCUTS = (
    "вартон",
    "инъектирован",
    "стеклопластик",
)

_EXPLICIT_EMPTY = {
    "NO_COMMERCIAL_ENTRY",
    "INSUFFICIENT_EVIDENCE",
    "REVIEW_REQUIRED",
}


def _hypotheses(model_out: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(model_out.get("commercial_category_hypotheses") or [])


def validate_case(
    ref: ReferenceExpectation,
    model_out: Dict[str, Any],
    *,
    allowed_categories: Set[str],
) -> Dict[str, Any]:
    verdict = "PASS"
    flags: List[str] = []
    hyps = _hypotheses(model_out)

    # subcategory presence
    for h in hyps:
        sub = h.get("subcategory_code") or h.get("commercial_subcategory_code")
        if not sub:
            if (h.get("subcategory_status") or "").upper() != "SUBCATEGORY_NOT_ASSIGNED":
                if not model_out.get("subcategory_explicit_ok"):
                    flags.append("SUBCATEGORY_SILENT_MISSING")
                    verdict = "REVIEW"

    tracks_seen = {(h.get("opportunity_track") or "").upper() for h in hyps}
    cats_seen = {
        (h.get("category_code") or h.get("commercial_category_code") or "").strip()
        for h in hyps
    }
    cats_seen.discard("")

    empty_status = (model_out.get("empty_hypothesis_status") or "").upper()
    pref_track = (model_out.get("preferred_opportunity_track") or "").upper()

    if not hyps:
        if empty_status == "SILENT_EMPTY_INVALID" or empty_status not in _EXPLICIT_EMPTY:
            flags.append("SILENT_EMPTY_HYPOTHESES")
            verdict = "FAIL"
        else:
            flags.append(f"EMPTY_EXPLICIT:{empty_status}")
            if pref_track:
                tracks_seen.add(pref_track)
            # Reference * with insufficient docs → REVIEW is acceptable for D
            if ref.expected_category == "*":
                if verdict == "PASS":
                    verdict = "REVIEW"
            else:
                verdict = "FAIL"

    expected_tracks = {t.upper() for t in ref.expected_tracks}
    if not tracks_seen.intersection(expected_tracks):
        # NO_COMMERCIAL_ENTRY explicit empty may omit design tracks → still FAIL vs expected design
        if empty_status == "NO_COMMERCIAL_ENTRY" and ref.expected_category == "*":
            flags.append("NO_COMMERCIAL_ENTRY_VS_EXPECTED_TRACK")
            verdict = "REVIEW"
        else:
            flags.append(f"WRONG_TRACK:got={sorted(tracks_seen)} want={sorted(expected_tracks)}")
            verdict = "FAIL"

    # category gate
    if hyps:
        if ref.expected_category != "*":
            if ref.expected_category not in cats_seen:
                flags.append(f"WRONG_CATEGORY:got={sorted(cats_seen)} want={ref.expected_category}")
                verdict = "FAIL"
        else:
            if not any(is_valid_commercial_category_code(c) and c in allowed_categories for c in cats_seen):
                flags.append("NO_VALID_COMMERCIAL_CATEGORY")
                verdict = "FAIL"
    elif ref.expected_category != "*" and empty_status not in _EXPLICIT_EMPTY:
        flags.append("NO_VALID_COMMERCIAL_CATEGORY")
        verdict = "FAIL"

    # semantic anti-shortcuts
    brands = [str(b).lower() for b in (model_out.get("brands") or [])]
    methods = [str(m).lower() for m in (model_out.get("work_methods") or [])]
    areas = [str(a).lower() for a in (model_out.get("application_areas") or [])]
    materials = [str(m).lower() for m in (model_out.get("material_signals") or [])]
    text_blob = " ".join(brands + methods + areas + materials)
    for bad in _FORBIDDEN_CATEGORY_SHORTCUTS:
        if bad in text_blob and bad not in (ref.auction_name or "").lower():
            flags.append(f"SEMANTIC_SHORTCUT_SIGNAL:{bad}")
            if verdict == "PASS":
                verdict = "REVIEW"

    if ref.case_key == "A_DIRECT_LIGHTING":
        if "lighting" not in cats_seen and any("вартон" in b for b in brands):
            flags.append("BRAND_TO_CATEGORY_LIGHTING")
            verdict = "FAIL"

    required_fields = [
        "procurement_form",
        "commercial_category_hypotheses",
        "material_signals",
        "work_methods",
        "application_areas",
        "object_context",
        "brands",
        "discovery_required",
    ]
    missing = [f for f in required_fields if f not in model_out]
    if missing:
        flags.append(f"MISSING_FIELDS:{missing}")
        if verdict == "PASS":
            verdict = "REVIEW"

    return {
        "case_key": ref.case_key,
        "procurement_id": ref.procurement_id,
        "verdict": verdict,
        "flags": flags,
        "tracks_seen": sorted(tracks_seen),
        "categories_seen": sorted(cats_seen),
        "expected_tracks": sorted(expected_tracks),
        "expected_category": ref.expected_category,
        "empty_hypothesis_status": empty_status or None,
    }


def aggregate_verdict(case_verdicts: List[Dict[str, Any]]) -> str:
    vs = [c.get("verdict") for c in case_verdicts]
    if any(v == "FAIL" for v in vs):
        return "FAIL"
    if any(v == "REVIEW" for v in vs):
        return "REVIEW"
    if vs and all(v == "PASS" for v in vs):
        return "PASS"
    return "FAIL"
