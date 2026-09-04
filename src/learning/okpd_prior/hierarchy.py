"""Hierarchical OKPD serialization and feature extraction.

Produces fail-safe hierarchical categorical features from raw OKPD codes:
- okpd_root   (e.g. '42')
- okpd_level2 (e.g. '42.11')
- okpd_level3 (e.g. '42.11.20')
- okpd_full   (e.g. '42.11.20.000')

Handles NULL, empty, malformed, and truncated codes gracefully.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Dict, Optional, Tuple

UNKNOWN_OKPD = "UNKNOWN_OKPD"
_VALID_OKPD_PATTERN = re.compile(r"^[0-9]+(\.[0-9]+)*$")


@dataclass(frozen=True)
class OKPDHierarchy:
    """Immutable representation of hierarchical OKPD features."""
    okpd_raw: Optional[str]
    okpd_root: str
    okpd_level2: str
    okpd_level3: str
    okpd_full: str

    def to_feature_dict(self) -> Dict[str, str]:
        """Returns feature dictionary for ML models."""
        return {
            "okpd_root": self.okpd_root,
            "okpd_level2": self.okpd_level2,
            "okpd_level3": self.okpd_level3,
            "okpd_full": self.okpd_full,
        }

    def format_signal_chain(self) -> str:
        """Returns human-readable hierarchy path, e.g. '42 → 42.11 → 42.11.20 → 42.11.20.000'."""
        if self.okpd_root == UNKNOWN_OKPD:
            return UNKNOWN_OKPD
        
        steps = []
        for val in (self.okpd_root, self.okpd_level2, self.okpd_level3, self.okpd_full):
            if not steps or steps[-1] != val:
                steps.append(val)
        return " → ".join(steps)


def parse_okpd_hierarchy(raw_code: Optional[str]) -> OKPDHierarchy:
    """Parses and normalizes an OKPD code into its 4-tier hierarchy.

    Args:
        raw_code: Raw string code from database or user input.

    Returns:
        OKPDHierarchy with root, level2, level3, and full representations.
    """
    if raw_code is None:
        return OKPDHierarchy(
            okpd_raw=None,
            okpd_root=UNKNOWN_OKPD,
            okpd_level2=UNKNOWN_OKPD,
            okpd_level3=UNKNOWN_OKPD,
            okpd_full=UNKNOWN_OKPD,
        )

    cleaned = raw_code.strip()
    if not cleaned or not _VALID_OKPD_PATTERN.match(cleaned):
        return OKPDHierarchy(
            okpd_raw=raw_code,
            okpd_root=UNKNOWN_OKPD,
            okpd_level2=UNKNOWN_OKPD,
            okpd_level3=UNKNOWN_OKPD,
            okpd_full=UNKNOWN_OKPD,
        )

    parts = [p for p in cleaned.split(".") if p]
    if not parts:
        return OKPDHierarchy(
            okpd_raw=raw_code,
            okpd_root=UNKNOWN_OKPD,
            okpd_level2=UNKNOWN_OKPD,
            okpd_level3=UNKNOWN_OKPD,
            okpd_full=UNKNOWN_OKPD,
        )

    root = parts[0]
    level2 = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else root
    level3 = f"{parts[0]}.{parts[1]}.{parts[2]}" if len(parts) >= 3 else level2
    full = ".".join(parts)

    return OKPDHierarchy(
        okpd_raw=raw_code,
        okpd_root=root,
        okpd_level2=level2,
        okpd_level3=level3,
        okpd_full=full,
    )
