"""Deterministic-first arbitration for initial-pass (operational decision).

A deterministic ``RoutingDecisionV3`` is classified into one of:

  * DETERMINISTIC_ACCEPT  - one clear commercial category, persist preliminary.
  * QWEN_REQUIRED         - genuinely ambiguous, only these reach Qwen.
  * NO_COMMERCIAL_ENTRY   - no commercial hypothesis from priors.

This is operational scheduling provenance, NOT a permanent business truth.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

MODE_ACCEPT = "DETERMINISTIC_ACCEPT"
MODE_QWEN = "QWEN_REQUIRED"
MODE_NO_ENTRY = "NO_COMMERCIAL_ENTRY"

REASON_NO_HYPOTHESIS = "NO_COMMERCIAL_HYPOTHESIS"
REASON_DISCOVERY = "DISCOVERY_REQUIRED"
REASON_MULTIPLE = "MULTIPLE_STRONG_CATEGORIES"
REASON_ACCEPT = "SINGLE_CLEAR_CATEGORY"


def arbitrate_deterministic(decision: Any) -> Tuple[str, str, Optional[Any]]:
    """Return (mode, reason, chosen_hypothesis_or_None)."""
    hypotheses = list(decision.commercial_category_hypotheses or [])
    if getattr(decision, "discovery_required", False):
        return MODE_QWEN, REASON_DISCOVERY, None
    if not hypotheses:
        return MODE_NO_ENTRY, REASON_NO_HYPOTHESIS, None
    categories = {h.commercial_category_code for h in hypotheses}
    if len(categories) > 1:
        return MODE_QWEN, REASON_MULTIPLE, None
    chosen = max(hypotheses, key=lambda h: float(getattr(h, "category_confidence", 0) or 0))
    return MODE_ACCEPT, REASON_ACCEPT, chosen
