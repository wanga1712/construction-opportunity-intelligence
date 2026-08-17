"""Aggregate document outcomes with uncertainty. 1/1 is not 100%."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from math import sqrt

from src.services.document_learning.contract import (
    PROVENANCE,
    DocumentObservation,
    normalize_source_token,
    normalize_title_signal,
)

USEFUL = "USEFUL_COMMERCIAL_EVIDENCE"
NO_EVIDENCE = "PARSED_NO_COMMERCIAL_EVIDENCE"
DOWNLOAD_FAIL = "DOWNLOAD_FAILED"
PARSE_FAIL = "PARSE_FAILED"
UNSUPPORTED = "UNSUPPORTED_FORMAT"
EMPTY = "EMPTY_DOCUMENT"

_REQUIRED_GROUP_FIELDS = (
    "document_class",
    "observations",
    "download_successes",
    "download_failures",
    "parse_successes",
    "parse_failures",
    "useful_count",
    "no_evidence_count",
    "empirical_useful_rate",
    "wilson_low",
    "wilson_high",
)


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
    judged = [row for row in rows if row.usefulness_label in {USEFUL, NO_EVIDENCE}]
    useful = sum(1 for row in judged if row.usefulness_label == USEFUL)
    n = len(judged)
    rate, low, high = wilson_interval(useful, n)
    by_provenance = {policy: 0 for policy in PROVENANCE}
    by_provenance.update(Counter(row.acquisition_policy for row in rows))
    return {
        "n_total": len(rows),
        "n_observed": n,
        "n_useful": useful,
        "empirical_useful_rate": rate,
        "wilson_low": low,
        "wilson_high": high,
        "labels": dict(labels),
        "by_provenance": by_provenance,
        "point_estimate_is_certain": False,
    }


def _group_identity(row: DocumentObservation) -> tuple:
    doc_class = normalize_source_token(row.source_document_type)
    if doc_class:
        return ("class", doc_class)
    return (
        "signals",
        normalize_title_signal(row.document_title) or "",
        normalize_source_token(row.file_extension) or "",
        normalize_source_token(row.mime_type) or "",
    )


def _empty_group(identity: tuple) -> dict[str, object]:
    if identity[0] == "class":
        document_class, title_signal, file_extension, mime_type = identity[1], None, None, None
    else:
        document_class = None
        _, title_signal, file_extension, mime_type = identity
        title_signal = title_signal or None
        file_extension = file_extension or None
        mime_type = mime_type or None
    return {
        "document_class": document_class,
        "title_signal": title_signal,
        "file_extension": file_extension,
        "mime_type": mime_type,
        "observations": 0,
        "procurements": 0,
        "download_successes": 0,
        "download_failures": 0,
        "parse_successes": 0,
        "parse_failures": 0,
        "useful_count": 0,
        "no_evidence_count": 0,
        "empirical_useful_rate": None,
        "wilson_low": None,
        "wilson_high": None,
        "by_provenance": {policy: 0 for policy in PROVENANCE},
        "_procurement_ids": set(),
    }


def aggregate_by_document_class(
    observations: Iterable[DocumentObservation],
) -> list[dict[str, object]]:
    """Answer: for this class/type/title pattern, how often was there evidence?"""
    buckets: dict[tuple, dict[str, object]] = {}
    for row in observations:
        key = _group_identity(row)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = _empty_group(key)
            buckets[key] = bucket
        bucket["observations"] = int(bucket["observations"]) + 1
        bucket["_procurement_ids"].add(row.procurement_id)  # type: ignore[union-attr]
        bucket["by_provenance"][row.acquisition_policy] = (  # type: ignore[index]
            int(bucket["by_provenance"][row.acquisition_policy]) + 1  # type: ignore[index]
        )
        label = row.usefulness_label
        if label == DOWNLOAD_FAIL:
            bucket["download_failures"] = int(bucket["download_failures"]) + 1
        elif label != "UNOBSERVED":
            bucket["download_successes"] = int(bucket["download_successes"]) + 1
        if label in {PARSE_FAIL, UNSUPPORTED}:
            bucket["parse_failures"] = int(bucket["parse_failures"]) + 1
        elif label in {USEFUL, NO_EVIDENCE, EMPTY}:
            bucket["parse_successes"] = int(bucket["parse_successes"]) + 1
        if label == USEFUL:
            bucket["useful_count"] = int(bucket["useful_count"]) + 1
        elif label == NO_EVIDENCE:
            bucket["no_evidence_count"] = int(bucket["no_evidence_count"]) + 1

    results: list[dict[str, object]] = []
    for bucket in buckets.values():
        useful = int(bucket["useful_count"])
        judged = useful + int(bucket["no_evidence_count"])
        rate, low, high = wilson_interval(useful, judged)
        bucket["empirical_useful_rate"] = rate
        bucket["wilson_low"] = low
        bucket["wilson_high"] = high
        ids = bucket.pop("_procurement_ids")
        bucket["procurements"] = len(ids)
        results.append(bucket)
    results.sort(
        key=lambda item: (
            item["document_class"] or "",
            item["title_signal"] or "",
            item["file_extension"] or "",
        )
    )
    return results


def required_group_fields() -> tuple[str, ...]:
    return _REQUIRED_GROUP_FIELDS
