"""Global category↔OKPD priors — user-independent runtime."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence


def normalize_okpd_code(code: str) -> str:
    return re.sub(r"\s+", "", (code or "").strip())


def _prior_matches(
    code: str,
    pattern: str,
    match_type: str,
    ancestry: Optional[Sequence[str]],
) -> bool:
    mt = (match_type or "PREFIX").upper()
    if mt == "EXACT":
        return code == normalize_okpd_code(pattern)
    if ancestry is not None:
        pat = normalize_okpd_code(pattern)
        return any(
            anc == pat or prefix_matches(anc, pat, "PREFIX")
            for anc in ancestry
        )
    return prefix_matches(code, pattern, mt)


def prefix_matches(procurement_okpd: str, pattern: str, match_type: str) -> bool:
    """Deterministic EXACT/PREFIX without ambiguous SQL LIKE."""
    code = normalize_okpd_code(procurement_okpd)
    pattern = normalize_okpd_code(pattern)
    if not code or not pattern:
        return False
    if match_type == "EXACT":
        return code == pattern
    if not code.startswith(pattern):
        return False
    if len(code) == len(pattern):
        return True
    return code[len(pattern)] == "."


def match_okpd_priors(
    okpd_code: str,
    priors: List[Dict[str, Any]],
    *,
    ancestry_codes: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Return all matching priors for an OKPD code. ONE_OKPD_ONE_CATEGORY=NO.

    When parent_id ancestry is provided, PREFIX/BRANCH match against ancestor
    nodes from the canonical climb — not a free string-prefix scan of unrelated codes.
    """
    if not okpd_code:
        return []

    code = normalize_okpd_code(okpd_code)
    ancestry = [normalize_okpd_code(c) for c in (ancestry_codes or []) if c]
    if code and code not in ancestry:
        ancestry = [code] + ancestry
    use_ancestry = bool(ancestry_codes)

    matched: List[Dict[str, Any]] = []
    for prior in priors:
        if not prior.get("active", True):
            continue
        pattern = str(prior.get("okpd_pattern") or "").strip()
        if not pattern:
            continue
        match_type = (prior.get("match_type") or "PREFIX").upper()
        if _prior_matches(code, pattern, match_type, ancestry if use_ancestry else None):
            matched.append(prior)

    matched.sort(
        key=lambda p: (
            -len(str(p.get("okpd_pattern") or "")),
            -float(p.get("prior_weight") or 0),
        )
    )
    return matched


def load_okpd_priors_from_db(crm_db) -> List[Dict[str, Any]]:
    """Load global priors — no user_id filter (RUNTIME_USER_OKPD_DEPENDENCY=NO)."""
    try:
        rows = crm_db.execute_query(
            """
            SELECT commercial_category_code, okpd_pattern, match_type, prior_weight,
                   signal_role, prior_kind, active, provenance, source_table, source_row_id,
                   source_user_id, registry_version
            FROM crm_category_okpd_priors
            WHERE active = TRUE
            ORDER BY prior_weight DESC, okpd_pattern
            """
        ) or []
    except Exception:
        rows = crm_db.execute_query(
            """
            SELECT commercial_category_code, okpd_pattern, match_type, prior_weight,
                   signal_role, active, provenance, source_table, source_row_id,
                   source_user_id, registry_version
            FROM crm_category_okpd_priors
            WHERE active = TRUE
            ORDER BY prior_weight DESC, okpd_pattern
            """
        ) or []
    return [dict(r) if isinstance(r, dict) else {} for r in rows]


def priors_for_category(
    okpd_code: str,
    priors: List[Dict[str, Any]],
    category_code: str,
) -> List[Dict[str, Any]]:
    return [
        p
        for p in match_okpd_priors(okpd_code, priors)
        if p.get("commercial_category_code") == category_code
    ]


ADMISSION_TARGET = "TARGET"
ADMISSION_OUT_OF_TARGET = "OUT_OF_TARGET"
ADMISSION_UNKNOWN_OKPD = "UNKNOWN_OKPD"


def classify_target_okpd(
    okpd_code: Optional[str],
    priors: List[Dict[str, Any]],
    *,
    ancestry_codes: Optional[List[str]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Canonical deterministic admission helper for OKPD target classification.

    Returns:
        (classification, matched_target_priors)
        where classification is one of:
          - 'UNKNOWN_OKPD': no OKPD, blank, or unresolved
          - 'TARGET': OKPD matches active canonical target priors
          - 'OUT_OF_TARGET': OKPD is present but has no matching active target priors
    """
    raw_code = str(okpd_code or "").strip()
    if not raw_code:
        return ADMISSION_UNKNOWN_OKPD, []

    norm = normalize_okpd_code(raw_code)
    if not norm:
        return ADMISSION_UNKNOWN_OKPD, []

    matched = match_okpd_priors(norm, priors, ancestry_codes=ancestry_codes)
    if matched:
        return ADMISSION_TARGET, matched
    return ADMISSION_OUT_OF_TARGET, []

