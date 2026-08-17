"""Document-learning observation contract.

Usefulness is derived from actual extraction outcomes, never from a selector
model's opinion. HISTORICAL_FILTERED rows are biased provenance, not
calibration truth.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

POLICY_VERSION = "DOCUMENT_ACQUISITION_POLICY_V1"

PROVENANCE = (
    "EXHAUSTIVE",
    "MODEL_SELECTED",
    "RANDOM_EXPLORATION",
    "HISTORICAL_FILTERED",
)

USEFULNESS_LABELS = (
    "USEFUL",
    "NOT_USEFUL",
    "UNOBSERVED",
    "DOWNLOAD_FAILED",
    "PARSE_FAILED",
)

_OK_STATUSES = {None, "", "OK", "SUCCESS"}


@dataclass
class DocumentObservation:
    procurement_id: int
    acquisition_policy: str
    acquisition_policy_version: str = POLICY_VERSION
    source_contour: str | None = None
    source_document_id: str | None = None
    source_document_url: str | None = None
    document_title: str | None = None
    source_document_type: str | None = None
    file_extension: str | None = None
    mime_type: str | None = None
    source_section: str | None = None
    procurement_form: str | None = None
    object_type: str | None = None
    object_context: str | None = None
    commercial_candidate_categories: list[str] = field(default_factory=list)
    okpd_context: str | None = None
    procurement_lifecycle: str | None = None
    document_ordinal: int | None = None
    document_count: int | None = None
    download_status: str | None = None
    parse_status: str | None = None
    file_size: int | None = None
    page_count: int | None = None
    text_length: int | None = None
    commercial_evidence_found: bool | None = None
    evidence_count: int | None = None
    matched_categories: list[str] = field(default_factory=list)
    matched_subcategories: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)
    product_mentions: list[str] = field(default_factory=list)
    specification_evidence: bool | None = None
    estimate_evidence: bool | None = None
    volume_quantity_evidence: bool | None = None
    numeric_unit_evidence: bool | None = None
    usefulness_label: str = "UNOBSERVED"
    extractor_version: str | None = None
    matcher_version: str | None = None
    taxonomy_version: str | None = None
    selector_model_version: str | None = None
    calibration_truth: bool = True

    def __post_init__(self) -> None:
        if self.acquisition_policy not in PROVENANCE:
            raise ValueError(f"unknown provenance: {self.acquisition_policy}")
        if self.usefulness_label not in USEFULNESS_LABELS:
            raise ValueError(f"unknown usefulness_label: {self.usefulness_label}")
        if self.acquisition_policy == "HISTORICAL_FILTERED":
            self.calibration_truth = False

    def observation_key(self) -> str:
        doc = self.source_document_id or self.source_document_url or ""
        return (
            f"{self.procurement_id}:{doc}:"
            f"{self.acquisition_policy}:{self.acquisition_policy_version}"
        )

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["observation_key"] = self.observation_key()
        return record


def usefulness_from_extraction(
    *,
    download_status: str | None = None,
    parse_status: str | None = None,
    commercial_evidence_found: bool | None = None,
    evidence_count: int | None = None,
    selector_score: float | None = None,
) -> str:
    """Label usefulness from extraction outcomes only.

    ``selector_score`` is accepted so callers cannot accidentally treat it as
    evidence: it is ignored.
    """
    del selector_score
    if download_status not in _OK_STATUSES:
        return "DOWNLOAD_FAILED"
    if parse_status not in _OK_STATUSES:
        return "PARSE_FAILED"
    if commercial_evidence_found or (evidence_count or 0) > 0:
        return "USEFUL"
    if download_status is None and parse_status is None:
        return "UNOBSERVED"
    return "NOT_USEFUL"
