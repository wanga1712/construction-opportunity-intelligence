"""Category admission gate — single authority for "is this our category?".

Separates CATEGORY ADMISSION from SCORING (WIP NEGATIVE-CONTROL-ADMISSION-GATE):

    procurement -> scope/track -> CATEGORY ADMISSION -> SCORING -> medal

Invariant (fail-closed):

    NO POSITIVE CATEGORY SIGNAL  ->  NO CATEGORY SCORING  ->  medal = NONE

Default/fallback scoring components (object_fit, commercial_timing,
commercial_scale, source_confidence, stage_actionability) are NOT a category
signal: they may refine the score of an already-admitted opportunity but must
never create the fact "this is our category".

Semantic contract:

    GOLD/SILVER/BRONZE/WOOD = our commercial opportunity, different strength
    NONE / rejected         = not our commercial opportunity at all

A ready-to-move-in housing purchase is "NONE", never WOOD.

Read-only and deterministic: no DB access, no model calls.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

ADMISSION_POLICY_VERSION = "category_admission_v1_no_default_opportunity"

#: Reason codes produced by real production category sources.
OKPD_PRIOR_REASON_CODES = frozenset({"okpd_prior", "okpd_match", "OKPD_MATCH"})
OBJECT_PRIOR_REASON_CODES = frozenset({"object_mode_contextual_prior"})
DIRECT_EVIDENCE_REASON_CODES = frozenset(
    {"direct_product_evidence_from_independent_source"}
)

#: Evidence roles that represent an explicit commercial/category entry point.
DIRECT_EVIDENCE_ROLES = frozenset(
    {"COMMERCIAL_PRODUCT_PRIOR", "DIRECT_CATEGORY_EVIDENCE"}
)

SIGNAL_OKPD_CATEGORY_PRIOR = "OKPD_CATEGORY_PRIOR"
SIGNAL_OBJECT_CATEGORY_PRIOR = "OBJECT_CATEGORY_PRIOR"
SIGNAL_DIRECT_CATEGORY_EVIDENCE = "DIRECT_CATEGORY_EVIDENCE"
SIGNAL_DIRECT_PRODUCT_EVIDENCE = "DIRECT_PRODUCT_EVIDENCE"
SIGNAL_POSITIVE_EVIDENCE = "POSITIVE_EVIDENCE"
SIGNAL_CATEGORY_CONFIDENCE = "CATEGORY_CONFIDENCE"
SIGNAL_NONE = "NO_POSITIVE_CATEGORY_SIGNAL"


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        stripped = value.strip()
        return stripped not in ("", "[]", "null", "None")
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return bool(value)


def _reason_codes(hypothesis: Dict[str, Any]) -> set:
    raw = hypothesis.get("reason_codes")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {str(code).strip() for code in raw if str(code).strip()}


def category_confidence(hypothesis: Dict[str, Any]) -> float:
    """Confidence used by scoring; model/prior derived, never a bare default."""
    for key in ("category_confidence", "confidence"):
        if hypothesis.get(key) is not None:
            return _as_float(hypothesis.get(key))
    semantic = hypothesis.get("semantic_hypothesis")
    if isinstance(semantic, dict):
        for key in ("confidence", "category_confidence"):
            if semantic.get(key) is not None:
                return _as_float(semantic.get(key))
    return 0.0


def has_admissible_category_signal(
    hypothesis: Dict[str, Any],
) -> Tuple[bool, str]:
    """Return (admissible, signal_source).

    ``admissible`` is True only when a real production category source exists.
    Generic scoring defaults are deliberately NOT accepted as a signal.
    """
    if not isinstance(hypothesis, dict):
        return False, SIGNAL_NONE

    # 1. Verified direct product/document entity evidence.
    if _non_empty(hypothesis.get("direct_product_evidence_sources")):
        return True, SIGNAL_DIRECT_PRODUCT_EVIDENCE

    # 2. Explicit commercial/direct category evidence role.
    role = str(hypothesis.get("evidence_role") or "").strip().upper()
    semantic = hypothesis.get("semantic_hypothesis")
    if not role and isinstance(semantic, dict):
        role = str(semantic.get("evidence_role") or "").strip().upper()
    if role in DIRECT_EVIDENCE_ROLES:
        return True, SIGNAL_DIRECT_CATEGORY_EVIDENCE

    reasons = _reason_codes(hypothesis)

    # 3. OKPD/category prior relation.
    if reasons & OKPD_PRIOR_REASON_CODES:
        return True, SIGNAL_OKPD_CATEGORY_PRIOR

    # 4. Object/category prior (real object classification, confirmation-gated).
    if reasons & OBJECT_PRIOR_REASON_CODES:
        return True, SIGNAL_OBJECT_CATEGORY_PRIOR

    # 5. Direct product-evidence reason code.
    if reasons & DIRECT_EVIDENCE_REASON_CODES:
        return True, SIGNAL_DIRECT_PRODUCT_EVIDENCE

    # 6. Positive evidence payload (object/document facts).
    if _non_empty(hypothesis.get("positive_evidence")):
        return True, SIGNAL_POSITIVE_EVIDENCE

    # 7. Non-zero category confidence (model/prior derived).
    if category_confidence(hypothesis) > 0.0:
        return True, SIGNAL_CATEGORY_CONFIDENCE

    return False, SIGNAL_NONE


def rejection_record(hypothesis: Dict[str, Any]) -> Dict[str, Any]:
    """Audit record for a hypothesis rejected by category admission."""
    ok, source = has_admissible_category_signal(hypothesis)
    return {
        "category_code": hypothesis.get("category_code")
        or hypothesis.get("commercial_category_code"),
        "opportunity_track": hypothesis.get("opportunity_track")
        or hypothesis.get("track"),
        "category_confidence": category_confidence(hypothesis),
        "evidence_role": hypothesis.get("evidence_role"),
        "reason_codes": list(hypothesis.get("reason_codes") or []),
        "has_positive_category_signal": ok,
        "signal_source": source,
        "admission_policy_version": ADMISSION_POLICY_VERSION,
    }


def filter_admissible_hypotheses(
    hypotheses: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split hypotheses into (admitted, rejected) by category admission."""
    admitted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for hypothesis in hypotheses or []:
        ok, _ = has_admissible_category_signal(hypothesis)
        if ok:
            admitted.append(hypothesis)
        else:
            rejected.append(rejection_record(hypothesis))
    return admitted, rejected


def admission_summary(rejections: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, Any]:
    """Compact counters for observability/reporting."""
    by_source: Dict[str, int] = {}
    by_track: Dict[str, int] = {}
    for item in rejections or []:
        source = str(item.get("signal_source") or SIGNAL_NONE)
        by_source[source] = by_source.get(source, 0) + 1
        track = str(item.get("opportunity_track") or "UNKNOWN")
        by_track[track] = by_track.get(track, 0) + 1
    return {
        "rejected": len(rejections or []),
        "by_source": by_source,
        "by_track": by_track,
        "admission_policy_version": ADMISSION_POLICY_VERSION,
    }
