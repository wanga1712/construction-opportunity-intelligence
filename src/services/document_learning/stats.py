"""Aggregate usefulness with uncertainty. 1/1 is not 100%."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from math import sqrt

from src.services.document_learning.contract import DocumentObservation


def wilson_interval(
    successes: int,
    n: int,
    z: float = 1.96,
) -> tuple[float | None, float | None, float | None]:
    if n <= 0:
        return None, None, None
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    margin = z * sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n)) / denom
    low = max(0.0, center - margin)
    high = min(1.0, center + margin)
    return p, low, high


def aggregate_usefulness(
    observations: Iterable[DocumentObservation],
) -> dict[str, object]:
    rows = list(observations)
    labels = Counter(row.usefulness_label for row in rows)
    observed = [
        row
        for row in rows
        if row.usefulness_label in {"USEFUL", "NOT_USEFUL"}
    ]
    useful = sum(1 for row in observed if row.usefulness_label == "USEFUL")
    n = len(observed)
    rate, low, high = wilson_interval(useful, n)
    by_provenance: dict[str, int] = Counter(row.acquisition_policy for row in rows)
    return {
        "n_total": len(rows),
        "n_observed": n,
        "n_useful": useful,
        "empirical_useful_rate": rate,
        "wilson_low": low,
        "wilson_high": high,
        "labels": dict(labels),
        "by_provenance": dict(by_provenance),
        "point_estimate_is_certain": False,
    }
