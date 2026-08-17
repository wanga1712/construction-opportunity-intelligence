"""Document-learning observation contract.

Outcomes come from actual processing/extraction only, never from a selector
or model opinion. Failures are not collapsed into a generic no-evidence label.
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

CALIBRATION_TRUTH_BY_PROVENANCE = {
    "EXHAUSTIVE": True,
    "RANDOM_EXPLORATION": True,
    "MODEL_SELECTED": False,
    "HISTORICAL_FILTERED": False,
}

OUTCOME_LABELS = (
    "USEFUL_COMMERCIAL_EVIDENCE",
    "PARSED_NO_COMMERCIAL_EVIDENCE",
    "DOWNLOAD_FAILED",
    "PARSE_FAILED",
    "UNSUPPORTED_FORMAT",
    "EMPTY_DOCUMENT",
    "DUPLICATE_DOCUMENT",
    "UNOBSERVED",
)
USEFULNESS_LABELS = OUTCOME_LABELS

_DOWNLOAD_FAIL = {"FAILED", "ERROR", "TIMEOUT", "DOWNLOAD_FAILED"}
_PARSE_FAIL = {"FAILED", "ERROR", "PARSE_FAILED"}
_UNSUPPORTED = {"UNSUPPORTED", "UNSUPPORTED_FORMAT"}
_EMPTY = {"EMPTY", "EMPTY_DOCUMENT"}
_DUPLICATE = {"DUPLICATE", "DUPLICATE_DOCUMENT"}


def calibration_truth_for(acquisition_policy: str) -> bool:
    try:
        return CALIBRATION_TRUTH_BY_PROVENANCE[acquisition_policy]
    except KeyError as exc:
        raise ValueError(f"unknown provenance: {acquisition_policy}") from exc


def normalize_source_token(value: str | None) -> str | None:
    """Whitespace-normalize a source metadata token. Never invent a class."""
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def normalize_title_signal(value: str | None) -> str | None:
    """Retain a title as a grouping signal without classifying it."""
    text = normalize_source_token(value)
    return text.casefold() if text else None


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
    calibration_truth: bool = False

    def __post_init__(self) -> None:
        if self.acquisition_policy not in PROVENANCE:
            raise ValueError(f"unknown provenance: {self.acquisition_policy}")
        if self.usefulness_label not in OUTCOME_LABELS:
            raise ValueError(f"unknown usefulness_label: {self.usefulness_label}")
        self.calibration_truth = calibration_truth_for(self.acquisition_policy)

    def observation_key(self) -> str:
        doc = self.source_document_id or self.source_document_url or ""
        return (
            f"{self.procurement_id}:{doc}:"
            f"{self.acquisition_policy}:{self.acquisition_policy_version}"
        )

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["observation_key"] = self.observation_key()
        record["calibration_truth"] = calibration_truth_for(self.acquisition_policy)
        return record


def outcome_from_extraction(
    *,
    download_status: str | None = None,
    parse_status: str | None = None,
    commercial_evidence_found: bool | None = None,
    evidence_count: int | None = None,
    file_size: int | None = None,
    text_length: int | None = None,
    page_count: int | None = None,
    is_duplicate: bool = False,
    selector_score: float | None = None,
) -> str:
    """Factual processing outcome. ``selector_score`` is ignored."""
    del selector_score
    download = (download_status or "").strip().upper()
    parse = (parse_status or "").strip().upper()

    if is_duplicate or download in _DUPLICATE or parse in _DUPLICATE:
        return "DUPLICATE_DOCUMENT"
    if download in _DOWNLOAD_FAIL:
        return "DOWNLOAD_FAILED"
    if download_status is None and parse_status is None:
        return "UNOBSERVED"
    if parse in _UNSUPPORTED:
        return "UNSUPPORTED_FORMAT"
    if parse in _PARSE_FAIL:
        return "PARSE_FAILED"
    if parse in _EMPTY:
        return "EMPTY_DOCUMENT"
    if parse_status is None:
        return "UNOBSERVED"
    if parse not in {"OK", "SUCCESS"}:
        return "PARSE_FAILED"
    if _is_empty_document(file_size=file_size, text_length=text_length, page_count=page_count):
        return "EMPTY_DOCUMENT"
    if commercial_evidence_found or (evidence_count or 0) > 0:
        return "USEFUL_COMMERCIAL_EVIDENCE"
    return "PARSED_NO_COMMERCIAL_EVIDENCE"


def _is_empty_document(
    *,
    file_size: int | None,
    text_length: int | None,
    page_count: int | None,
) -> bool:
    if file_size == 0:
        return True
    if text_length == 0 and (page_count is None or page_count == 0):
        return True
    return False


def usefulness_from_extraction(**kwargs: Any) -> str:
    """Alias kept for call-sites; returns factual outcome labels."""
    return outcome_from_extraction(**kwargs)
