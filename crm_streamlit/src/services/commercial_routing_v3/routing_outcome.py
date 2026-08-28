"""Structured routing outcome — Phase 6B namespace separation.

Invariant: model_validated is never mutated after construction.
Business enrichment operates on deep copies / separate structures.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RoutingOutcome:
    """Separated MODEL / BUSINESS / provenance contract.

    compatibility_normalized_result remains for legacy consumers and is
    explicitly NOT model authority (see NORMALIZED_RESULT_IS_MODEL_AUTHORITY=NO).
    """

    inference_run_id: Optional[int]
    model_validated: Dict[str, Any]
    model_derived: Dict[str, Any] = field(default_factory=dict)
    business_result: Dict[str, Any] = field(default_factory=dict)
    field_provenance: Dict[str, str] = field(default_factory=dict)
    compatibility_normalized_result: Dict[str, Any] = field(default_factory=dict)
    decision: Any = None  # RoutingDecisionV3 for callers that still need it

    def frozen_model(self) -> Dict[str, Any]:
        """Deep copy of validated model — safe for callers."""
        return copy.deepcopy(self.model_validated)

    def assert_model_unmutated(self, original: Dict[str, Any]) -> None:
        if self.model_validated != original:
            raise AssertionError("MODEL_VALIDATED_MUTATED_IN_MEMORY")


def model_derived_overall_confidence(model_validated: Dict[str, Any]) -> Optional[float]:
    """Max hypothesis confidence from validated model only (MODEL_DERIVED).

    Preserves 0.0. Returns None when no hypothesis confidence fields exist.
    """
    hyps = model_validated.get("commercial_category_hypotheses") or []
    if not isinstance(hyps, list) or not hyps:
        return None
    vals: List[float] = []
    for h in hyps:
        if not isinstance(h, dict):
            continue
        if "confidence" not in h and "category_confidence" not in h:
            continue
        raw = h.get("confidence", h.get("category_confidence"))
        if raw is None:
            continue
        vals.append(float(raw))
    if not vals:
        return None
    return max(vals)
