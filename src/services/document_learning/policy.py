"""Acquisition mix for future document processing. No downloads here."""
from __future__ import annotations

from collections.abc import Sequence
from random import Random

from src.services.document_learning.config import AUTOMATIC_SKIP_ENABLED
from src.services.document_learning.contract import POLICY_VERSION

SELF_SELECTED_ONLY = "SELF_SELECTED_ONLY"
HISTORICAL_FILTERED_IS_BIASED = "HISTORICAL_FILTERED_IS_BIASED"
EMPTY_SET = "EMPTY_SET"


def assign_provenance(
    document_ids: Sequence[str],
    selected_ids: Sequence[str],
    *,
    exhaustive: bool,
    exploration_rate: float,
    rng: Random | None = None,
) -> dict[str, str]:
    """Return id → provenance. Never marks unobserved docs as skip-to-train."""
    if AUTOMATIC_SKIP_ENABLED:
        raise RuntimeError("automatic document skip is forbidden in this baseline")
    assigned: dict[str, str] = {}
    selected = set(selected_ids)
    if exhaustive:
        return {doc_id: "EXHAUSTIVE" for doc_id in document_ids}

    remainder = [doc_id for doc_id in document_ids if doc_id not in selected]
    explore_n = int(round(len(document_ids) * exploration_rate))
    explore_n = min(len(remainder), max(0, explore_n))
    picker = rng or Random(0)
    explored = set(picker.sample(remainder, explore_n)) if explore_n else set()

    for doc_id in document_ids:
        if doc_id in selected:
            assigned[doc_id] = "MODEL_SELECTED"
        elif doc_id in explored:
            assigned[doc_id] = "RANDOM_EXPLORATION"
        else:
            assigned[doc_id] = "UNOBSERVED"
    return assigned


def training_eligibility(provenances: Sequence[str]) -> dict[str, str | bool]:
    """A training set of only self-selected docs is ineligible."""
    policies = {p for p in provenances if p and p != "UNOBSERVED"}
    if not policies:
        return {"eligible": False, "reason": EMPTY_SET}
    if policies <= {"MODEL_SELECTED"}:
        return {"eligible": False, "reason": SELF_SELECTED_ONLY}
    if "HISTORICAL_FILTERED" in policies and policies <= {
        "HISTORICAL_FILTERED",
        "MODEL_SELECTED",
    }:
        return {"eligible": False, "reason": HISTORICAL_FILTERED_IS_BIASED}
    return {"eligible": True, "reason": "OK", "policy_version": POLICY_VERSION}
