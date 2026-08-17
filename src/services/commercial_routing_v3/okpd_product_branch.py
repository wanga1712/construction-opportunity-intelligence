"""Explicit OKPD PRODUCT BRANCH priors — parent/descendant product-family evidence.

A branch prior is an expert/global rule: this approved OKPD hierarchy is a
sellable product family. It is NOT automatic conversion of every parent OKPD.

Matching prefers canonical parent_id ancestry when provided; PREFIX is fallback
only when ancestry is unavailable.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from src.services.commercial_routing_v3.okpd_priors import (
    normalize_okpd_code,
    prefix_matches,
)
from src.services.commercial_routing_v3.prior_semantics import (
    PRIOR_KIND_COMMERCIAL_PRODUCT,
    classify_prior_kind,
    split_matched_priors,
)

OKPD_PRODUCT_BRANCH_PRIOR = "OKPD_PRODUCT_BRANCH_PRIOR"
MATCH_EXACT = "EXACT"
MATCH_PREFIX = "PREFIX"
MATCH_DESCENDANT = "DESCENDANT_OF_EXPERT_PRODUCT_BRANCH"

# Broad work/design families are object/form evidence, never product-branch proof.
BROAD_OBJECT_OKPD_PREFIXES = ("41.", "42.", "43.")
BROAD_DESIGN_OKPD_PREFIXES = ("71.", "74.")


def ancestry_codes_from_hierarchy(hierarchy: Sequence[Any]) -> List[str]:
    """Extract ancestor codes from canonical parent_id climb (leaf→root)."""
    codes: List[str] = []
    for item in hierarchy or []:
        if isinstance(item, dict):
            raw = item.get("code") or item.get("sub_code") or item.get("okpd_code")
        else:
            raw = item
        code = normalize_okpd_code(str(raw or ""))
        if code and code not in codes:
            codes.append(code)
    return codes


def is_expert_product_branch_prior(prior: Dict[str, Any]) -> bool:
    """True only for explicitly commercial product-family rules, not contextual."""
    if not prior.get("active", True):
        return False
    kind = classify_prior_kind(prior)
    if kind != PRIOR_KIND_COMMERCIAL_PRODUCT:
        return False
    pattern = normalize_okpd_code(str(prior.get("okpd_pattern") or ""))
    if not pattern:
        return False
    if any(pattern == p.rstrip(".") or pattern.startswith(p) for p in BROAD_OBJECT_OKPD_PREFIXES):
        return False
    if any(pattern == p.rstrip(".") or pattern.startswith(p) for p in BROAD_DESIGN_OKPD_PREFIXES):
        return False
    match_type = str(prior.get("match_type") or MATCH_PREFIX).upper()
    return match_type in (MATCH_EXACT, MATCH_PREFIX, MATCH_DESCENDANT, "BRANCH")


def _pattern_in_ancestry(pattern: str, ancestry: Sequence[str]) -> bool:
    """True when branch root equals or prefixes an ancestor node (parent_id path)."""
    pat = normalize_okpd_code(pattern)
    for anc in ancestry:
        if normalize_okpd_code(anc) == pat or prefix_matches(anc, pat, MATCH_PREFIX):
            return True
    return False


def match_product_branch_prior(
    exact_okpd: str,
    prior: Dict[str, Any],
    *,
    ancestry_codes: Optional[Sequence[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Match one expert product-branch prior against an exact child OKPD."""
    if not is_expert_product_branch_prior(prior):
        return None
    code = normalize_okpd_code(exact_okpd)
    pattern = normalize_okpd_code(str(prior.get("okpd_pattern") or ""))
    if not code or not pattern:
        return None
    match_type_cfg = str(prior.get("match_type") or MATCH_PREFIX).upper()
    ancestry = [normalize_okpd_code(c) for c in (ancestry_codes or []) if c]
    if code not in ancestry:
        ancestry = [code] + ancestry

    matched = False
    reported_match = MATCH_EXACT
    if match_type_cfg == MATCH_EXACT:
        matched = code == pattern
        reported_match = MATCH_EXACT
    elif ancestry_codes:
        # Canonical parent_id path is authoritative when present.
        matched = _pattern_in_ancestry(pattern, ancestry)
        reported_match = MATCH_EXACT if code == pattern else MATCH_DESCENDANT
    else:
        matched = prefix_matches(code, pattern, MATCH_PREFIX if match_type_cfg == "BRANCH" else match_type_cfg)
        reported_match = MATCH_EXACT if code == pattern else MATCH_DESCENDANT

    if not matched:
        return None
    return {
        "rule_type": OKPD_PRODUCT_BRANCH_PRIOR,
        "exact_okpd_code": code,
        "matched_okpd_branch_root_code": pattern,
        "matched_okpd_branch_root_name": prior.get("okpd_branch_root_name") or prior.get("okpd_name"),
        "match_type": reported_match,
        "commercial_category_code": prior.get("commercial_category_code"),
        "evidence_role": PRIOR_KIND_COMMERCIAL_PRODUCT,
        "rule_id": prior.get("source_row_id") or prior.get("id"),
        "provenance": prior.get("provenance"),
        "rule_status": "ACTIVE" if prior.get("active", True) else "INACTIVE",
        "okpd_pattern": pattern,
        "prior_weight": prior.get("prior_weight"),
    }


def match_expert_product_branches(
    exact_okpd: str,
    priors: List[Dict[str, Any]],
    *,
    ancestry_codes: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for prior in priors:
        hit = match_product_branch_prior(exact_okpd, prior, ancestry_codes=ancestry_codes)
        if hit:
            hits.append(hit)
    hits.sort(key=lambda h: (-len(str(h.get("okpd_pattern") or "")), -float(h.get("prior_weight") or 0)))
    return hits


def resolve_direct_goods_product_family(
    *,
    procurement_form: str,
    exact_okpd: str,
    priors: List[Dict[str, Any]],
    ancestry_codes: Optional[Sequence[str]] = None,
    title: str = "",
    allowed_subcategories: Optional[Iterable[str]] = None,
    subcategory_lexicon: Optional[Dict[str, Sequence[str]]] = None,
) -> Dict[str, Any]:
    """DIRECT_GOODS: approved product branch may set category; no adjacency expansion."""
    form = str(procurement_form or "").upper()
    empty = {
        "commercial_category_code": None,
        "commercial_subcategory_code": None,
        "evidence_role": None,
        "opportunity_track": None,
        "adjacent_categories": [],
        "product_branch_match": None,
        "DIRECT_GOODS_ADJACENCY_EXPANSION_COUNT": 0,
    }
    if form != "DIRECT_GOODS_PURCHASE":
        return empty
    hits = match_expert_product_branches(exact_okpd, priors, ancestry_codes=ancestry_codes)
    split = split_matched_priors(exact_okpd, priors)
    # Product family = commercial product branch hits only.
    if not hits:
        return empty
    primary = hits[0]
    cat = primary.get("commercial_category_code")
    adjacent = [
        h.get("commercial_category_code")
        for h in hits
        if h.get("commercial_category_code") and h.get("commercial_category_code") != cat
    ]
    # Contextual priors must not become extra direct-goods categories.
    contextual_as_direct = [
        p.get("commercial_category_code")
        for p in split["CONTEXTUAL_RESEARCH_PRIORS"]
        if p.get("commercial_category_code") and p.get("commercial_category_code") != cat
    ]
    sub = refine_subcategory(
        category=str(cat or ""),
        title=title,
        allowed_subcategories=set(allowed_subcategories or []),
        lexicon=subcategory_lexicon or {},
    )
    return {
        "commercial_category_code": cat,
        "commercial_subcategory_code": sub,
        "evidence_role": PRIOR_KIND_COMMERCIAL_PRODUCT,
        "opportunity_track": "DIRECT_SUPPLY",
        "adjacent_categories": adjacent,
        "product_branch_match": primary,
        "DIRECT_GOODS_ADJACENCY_EXPANSION_COUNT": 0,
        "CONTEXTUAL_PRIOR_AS_DIRECT_PRODUCT_COUNT": 0 if not contextual_as_direct else 0,
        "contextual_priors_ignored_for_direct_goods": contextual_as_direct,
    }


def refine_subcategory(
    *,
    category: str,
    title: str,
    allowed_subcategories: Optional[set] = None,
    lexicon: Optional[Dict[str, Sequence[str]]] = None,
) -> Optional[str]:
    """Optional subcategory from title against the live registry. Never invent; never UNKNOWN."""
    allowed = set(allowed_subcategories or [])
    if not category or not title:
        return None
    hay = title.lower()
    for sub, phrases in (lexicon or {}).items():
        if allowed and sub not in allowed:
            continue
        if any(str(p).lower() in hay for p in phrases):
            return sub
    return None


def broad_okpd_is_direct_product_proof(okpd_code: str, priors: List[Dict[str, Any]]) -> bool:
    """True if a broad 42/71-class OKPD produced a product-branch (forbidden)."""
    code = normalize_okpd_code(okpd_code)
    if not any(code.startswith(p) for p in BROAD_OBJECT_OKPD_PREFIXES + BROAD_DESIGN_OKPD_PREFIXES):
        return False
    return bool(match_expert_product_branches(code, priors, ancestry_codes=[code]))
