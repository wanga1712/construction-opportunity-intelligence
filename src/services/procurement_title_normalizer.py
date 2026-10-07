"""Canonical procurement-title normalizer (single source of truth).

Used by the export script, the approved exact-title rule lookup and the
subcategory resolver/backfill so there is exactly one normalization behaviour
(no "export v1" vs "runtime v1-but-slightly-different" drift).

Behaviour (conservative, v1):

    Unicode NFKC -> lowercase -> ё->е -> NBSP -> space -> line breaks -> space
    -> punctuation -> space -> collapse repeated whitespace -> strip

Digits are never removed: ``сервер 2u``, ``220 кв``, ``110 кв`` stay distinct
groups. Model names, powers, voltages, sizes, years and equipment numbers are
preserved (normalization only touches case / whitespace / punctuation).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

# Bump only with a coordinated re-import of approved rules.
NORMALIZATION_VERSION = "v1"

_WS_RE = re.compile(r"\s+")

# Non-breaking / narrow / fixed-width spaces and line/paragraph separators.
_SPACE_CHARS = (
    "\u00a0", "\u202f", "\u2007", "\u2009", "\u200a", "\ufeff",
    "\r", "\n", "\t", "\u2028", "\u2029", "\v", "\f",
)


def normalize_procurement_title_v1(title: Optional[str]) -> str:
    """Return the canonical v1 normalized form of a procurement title."""
    if title is None:
        return ""
    text = unicodedata.normalize("NFKC", str(title))
    text = text.lower().replace("\u0451", "\u0435")  # ё -> е
    for ch in _SPACE_CHARS:
        text = text.replace(ch, " ")
    # Punctuation -> space (keeps digits and letters untouched).
    text = "".join(
        " " if unicodedata.category(ch).startswith("P") else ch for ch in text
    )
    return _WS_RE.sub(" ", text).strip()
