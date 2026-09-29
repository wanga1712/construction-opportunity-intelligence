"""Main dashboard — value types and pure helpers (no DB access)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

MEDALS = ("GOLD", "SILVER", "BRONZE", "WOOD")

FRESH_GREEN_SEC = 300.0
FRESH_YELLOW_SEC = 1800.0


@dataclass
class LiveIndicator:
    label: str
    caption: str
    age_seconds: Optional[float] = None
    status: str = "UNKNOWN"
    stamp: Optional[datetime] = None
    error: Optional[str] = None


@dataclass
class Stage:
    key: str
    label: str
    count: Optional[int] = None
    error: Optional[str] = None


@dataclass
class CategoryRow:
    code: str
    name: str
    active: int = 0
    gold: int = 0
    silver: int = 0
    bronze: int = 0
    wood: int = 0
    second_pass: int = 0
    with_docs: int = 0
    waiting_docs: int = 0


@dataclass
class Opportunity:
    crm_id: int
    contract_number: str
    title: str
    effective_medal: str
    base_authority: str
    category: str
    category_medal: str
    initial_price: float
    days_left: Optional[float]


@dataclass
class ControlRoom:
    indicators: List[LiveIndicator] = field(default_factory=list)
    active_total: Optional[int] = None
    new_24h: Optional[int] = None
    with_docs: Optional[int] = None
    docs_complete: Optional[int] = None
    second_pass: Optional[int] = None
    model_authority: Optional[int] = None
    stages: List[Stage] = field(default_factory=list)
    gaps: Dict[str, Optional[int]] = field(default_factory=dict)
    categories: List[CategoryRow] = field(default_factory=list)
    opportunities: List[Opportunity] = field(default_factory=list)
    authority: Dict[str, int] = field(default_factory=dict)
    families: Dict[str, int] = field(default_factory=dict)
    deadlines: Dict[str, int] = field(default_factory=dict)
    decay_affected: Optional[int] = None
    doc_errors: List[Tuple[str, int]] = field(default_factory=list)
    doc_errors_total: Optional[int] = None
    errors: List[str] = field(default_factory=list)
    load_seconds: float = 0.0

    @property
    def authority_sum(self) -> int:
        return sum(self.authority.values())


def freshness_status(age_seconds: Optional[float]) -> str:
    if age_seconds is None:
        return "UNKNOWN"
    age = max(age_seconds, 0.0)
    if age <= FRESH_GREEN_SEC:
        return "GREEN"
    if age <= FRESH_YELLOW_SEC:
        return "YELLOW"
    return "RED"


def format_age(age_seconds: Optional[float]) -> str:
    if age_seconds is None:
        return "—"
    age = max(age_seconds, 0.0)
    if age < 60:
        return f"{int(age)} сек назад"
    if age < 3600:
        return f"{int(age // 60)} мин назад"
    if age < 86400:
        return f"{int(age // 3600)} ч назад"
    return f"{int(age // 86400)} дн назад"


def deadline_bucket(days_left: Optional[float]) -> str:
    if days_left is None:
        return "unknown"
    if days_left > 14:
        return "gt14"
    if days_left > 7:
        return "8-14"
    if days_left > 3:
        return "4-7"
    return "2-3"


def classify_doc_error(message: Optional[str], download_status: Optional[str]) -> str:
    """Deterministic class for a document failure. Never merges NO_LINKS."""
    text = (message or "").lower()
    status = (download_status or "").upper()
    if "uq_canonical_source_file_gen" in text or "duplicate key" in text or "unique constraint" in text:
        return "DUPLICATE_COLLISION"
    if "403" in text or "forbidden" in text:
        return "FORBIDDEN_403"
    if "too long" in text or "name too long" in text:
        return "FILENAME_TOO_LONG"
    if "unsupported format" in text:
        return "UNSUPPORTED"
    if "archive extraction failed" in text:
        return "BROKEN_ARCHIVE"
    if ("pdf" in text) and ("broken" in text or "malformed" in text or "cannot open" in text):
        return "MALFORMED_PDF"
    if "skip" in text:
        return "SKIPPED"
    if "download" in text or "validate" in text or "timeout" in text or "timed out" in text:
        return "DOWNLOAD_ERROR"
    if status == "FAILED":
        return "DOWNLOAD_ERROR"
    return "OTHER"


ERROR_LABELS: Dict[str, str] = {
    "DOWNLOAD_ERROR": "Download error",
    "FORBIDDEN_403": "403 / Forbidden",
    "MALFORMED_PDF": "Broken PDF",
    "BROKEN_ARCHIVE": "Broken archive",
    "DUPLICATE_COLLISION": "Duplicate",
    "FILENAME_TOO_LONG": "Filename too long",
    "UNSUPPORTED": "Unsupported",
    "SKIPPED": "Skipped",
    "OTHER": "Other",
}

AUTHORITY_LABELS: Dict[str, str] = {
    "EXPERT": "Expert",
    "SECOND_PASS_MODEL": "Second Pass",
    "PRELIMINARY": "Preliminary",
    "UNASSESSED": "Unassessed",
}

FAMILY_LABELS: Dict[str, str] = {
    "SOCIAL": "SOCIAL",
    "COMMERCIAL": "COMMERCIAL",
    "DIRECT_SUPPLY": "DIRECT_SUPPLY",
    "OTHER": "OTHER",
}

BUCKET_LABELS: Dict[str, str] = {
    "gt14": "> 14 дней",
    "8-14": "8–14 дней",
    "4-7": "4–7 дней",
    "2-3": "2–3 дня",
    "unknown": "без срока",
}