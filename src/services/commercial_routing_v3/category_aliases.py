"""Explicit canonical commercial category aliases — no fuzzy matching."""
from __future__ import annotations

from typing import Dict, Optional, Set

# Only aliases with an explicit registry target. Case-normalization for known codes.
CANONICAL_CATEGORY_ALIASES: Dict[str, str] = {
    "COMPUTERS": "computers",
    "Computers": "computers",
    "LIGHTING": "lighting",
    "FLOORING": "flooring",
    "WATERPROOFING": "waterproofing",
}


def resolve_explicit_category_alias(
    raw: str,
    *,
    allowed_categories: Set[str],
) -> Optional[str]:
    """Return canonical code only when alias maps to an allowed registry code."""
    if not raw:
        return None
    s = str(raw).strip()
    if s in allowed_categories:
        return s
    target = CANONICAL_CATEGORY_ALIASES.get(s)
    if target and target in allowed_categories:
        return target
    return None
