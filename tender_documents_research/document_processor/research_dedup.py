"""Canonical procurement research identity and non-destructive dedup rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ResearchIdentity:
    source_family: str
    notice_number: str | None
    procurement_id: int
    key: str


def canonical_research_identity(*, source_family: Any, notice_number: Any, procurement_id: Any) -> ResearchIdentity:
    """Resolve identity by notice within source family, with ID fallback."""
    family = str(source_family or "UNKNOWN_SOURCE").strip().lower()
    notice = str(notice_number or "").strip() or None
    identity_part = notice or f"procurement_id:{int(procurement_id)}"
    return ResearchIdentity(
        source_family=family,
        notice_number=notice,
        procurement_id=int(procurement_id),
        key=f"{family}:{identity_part}",
    )


def research_disposition(rows: Sequence[Mapping[str, Any]]) -> str:
    """Return the strongest existing state for one canonical identity."""
    statuses = {str(row.get("status") or "").upper() for row in rows}
    if "PROCESSING" in statuses:
        return "DO_NOT_ENQUEUE_DUPLICATE_PROCESSING"
    if any(
        str(row.get("status") or "").upper() == "COMPLETED"
        and bool(row.get("successful_parse"))
        for row in rows
    ):
        return "REUSE_EXISTING_RESEARCH"
    if statuses.intersection({"PENDING", "PRE_RESEARCH_WAITING"}):
        return "DO_NOT_ENQUEUE_DUPLICATE_PENDING"
    if statuses.intersection({"FAILED", "PARTIAL", "NO_LINKS"}):
        return "RETRY_EXISTING_IDENTITY"
    if "COMPLETED" in statuses:
        return "RETRY_EXISTING_IDENTITY"
    return "NEW_RESEARCH_ALLOWED"
