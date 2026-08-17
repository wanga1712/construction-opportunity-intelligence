"""Split OKPD priors into commercial-product vs contextual-research.

CRITICAL: 27.32 cable/wire OKPD must NOT assert cable_support_systems as a
direct commercial product. It is CONTEXTUAL_RESEARCH_PRIOR only
(search docs for trays/ladders/supports). Direct cable procurement without
another sellable product → expected NO_COMMERCIAL_ENTRY for product priors.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from src.services.commercial_routing_v3.okpd_priors import match_okpd_priors

PRIOR_KIND_COMMERCIAL_PRODUCT = "COMMERCIAL_PRODUCT_PRIOR"
PRIOR_KIND_CONTEXTUAL_RESEARCH = "CONTEXTUAL_RESEARCH_PRIOR"

# Patterns that are adjacency/context for a category, not direct product evidence.
# Keyed by (category_code, okpd_pattern_prefix).
CONTEXTUAL_ONLY_RULES: Dict[Tuple[str, str], str] = {
    ("cable_support_systems", "27.32"): (
        "OKPD 27.32 is cable/wire product — not cable tray/support systems. "
        "Contextual research only; do not expand cable→tray."
    ),
    ("cable_support_systems", "27.3"): (
        "Broad wire/cable group is contextual for cable support systems, not direct product."
    ),
    ("composite_cable_trays", "27.32"): (
        "OKPD 27.32 cable/wire is contextual adjacency for trays, not direct tray procurement."
    ),
    ("composite_cable_trays", "27.3"): (
        "Broad wire/cable group is contextual for composite trays, not direct product."
    ),
}

# Broad construction/works OKPD prefixes: materials categories are search hypotheses
# unless the OKPD itself is a sellable product code.
BROAD_WORKS_OKPD_PREFIXES = ("41.", "42.", "43.")
BROAD_WORKS_MATERIAL_CATEGORIES = {
    "flooring",
    "waterproofing",
    "lighting",
    "drainage_water_management",
    "curbstone",
    "composite_structures",
    "cable_support_systems",
    "composite_cable_trays",
}

# When these exact prefixes are the ONLY commercial-product prior hits for a
# direct-goods cable procurement, commercial product list is empty.
DIRECT_CABLE_OKPD_PREFIXES = ("27.32",)

DIRECT_CABLE_EXPECTED_RESULT = "NO_COMMERCIAL_ENTRY"


def classify_prior_kind(prior: Dict[str, Any]) -> str:
    """Return COMMERCIAL_PRODUCT_PRIOR or CONTEXTUAL_RESEARCH_PRIOR."""
    explicit = (prior.get("prior_kind") or prior.get("prior_type") or "").strip().upper()
    if explicit in (PRIOR_KIND_COMMERCIAL_PRODUCT, PRIOR_KIND_CONTEXTUAL_RESEARCH):
        return explicit
    # signal_role heuristics from legacy migration
    role = str(prior.get("signal_role") or "").upper()
    if role in ("CONTEXT_ONLY", "CONTEXTUAL", "RESEARCH_CONTEXT", "CANDIDATE_SIGNAL"):
        # CANDIDATE_SIGNAL historically mixed both — apply hard overrides below
        pass
    cat = str(prior.get("commercial_category_code") or "")
    pattern = str(prior.get("okpd_pattern") or "")
    for (c, pref), _reason in CONTEXTUAL_ONLY_RULES.items():
        if cat == c and (pattern == pref or pattern.startswith(pref + ".") or pattern.startswith(pref)):
            return PRIOR_KIND_CONTEXTUAL_RESEARCH
    # Broad works OKPD → material categories are contextual research only
    if cat in BROAD_WORKS_MATERIAL_CATEGORIES:
        if any(pattern == p.rstrip(".") or pattern.startswith(p) for p in BROAD_WORKS_OKPD_PREFIXES):
            return PRIOR_KIND_CONTEXTUAL_RESEARCH
    if role in ("CONTEXT_ONLY", "CONTEXTUAL", "RESEARCH_CONTEXT"):
        return PRIOR_KIND_CONTEXTUAL_RESEARCH
    if role in ("DIRECT_PRODUCT", "COMMERCIAL_PRODUCT", "PRODUCT"):
        return PRIOR_KIND_COMMERCIAL_PRODUCT
    # default: treat high-weight exact category product OKPDs as commercial;
    # construction fanout like 27.32→cable_support already caught above.
    return PRIOR_KIND_COMMERCIAL_PRODUCT


def split_matched_priors(
    okpd_code: str,
    priors: List[Dict[str, Any]],
    *,
    ancestry_codes: Optional[List[str]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    matched = match_okpd_priors(okpd_code, priors, ancestry_codes=ancestry_codes)
    commercial: List[Dict[str, Any]] = []
    contextual: List[Dict[str, Any]] = []
    for p in matched:
        kind = classify_prior_kind(p)
        enriched = dict(p)
        enriched["prior_kind"] = kind
        if kind == PRIOR_KIND_CONTEXTUAL_RESEARCH:
            contextual.append(enriched)
        else:
            commercial.append(enriched)
    return {
        "COMMERCIAL_PRODUCT_PRIORS": commercial,
        "CONTEXTUAL_RESEARCH_PRIORS": contextual,
        "matched_all": matched,
    }


def direct_cable_product_priors_empty(okpd_code: str, commercial: List[Dict[str, Any]]) -> bool:
    """True when OKPD is cable/wire and no non-cable-support commercial prior remains."""
    code = (okpd_code or "").strip()
    if not any(code == p or code.startswith(p + ".") for p in DIRECT_CABLE_OKPD_PREFIXES):
        return False
    # after split, commercial for cable_support from 27.32 should already be empty
    return len(commercial) == 0
