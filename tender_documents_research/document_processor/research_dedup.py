"""Canonical procurement research identity and non-destructive dedup rules."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ResearchIdentity:
    source_family: str
    notice_number: str | None
    procurement_id: int
    key: str


SUPPORTED_SOURCE_TABLE_FAMILIES = {
    "reestr_contract_44_fz": "44_FZ",
    "reestr_contract_44_fz_awarded": "44_FZ",
    "reestr_contract_44_fz_completed": "44_FZ",
    "reestr_contract_44_fz_commission_work": "44_FZ",
    "reestr_contract_44_fz_unclear": "44_FZ",
    "reestr_contract_44_fz_unknown": "44_FZ",
    "reestr_contract_223_fz": "223_FZ",
    "reestr_contract_223_fz_awarded": "223_FZ",
    "reestr_contract_223_fz_completed": "223_FZ",
    "reestr_contract_223_fz_commission_work": "223_FZ",
    "reestr_contract_223_fz_unclear": "223_FZ",
}


def normalize_source_family(source_table: Any) -> str:
    """Map an audited registry table variant to its supported law family."""
    table = str(source_table or "").strip().lower()
    try:
        return SUPPORTED_SOURCE_TABLE_FAMILIES[table]
    except KeyError as exc:
        raise ValueError(f"unsupported procurement source table: {source_table!r}") from exc


def _normalize_notice_number(notice_number: Any) -> str | None:
    notice = str(notice_number or "").strip()
    return re.sub(r"\s+", "", notice.upper()) or None


def canonical_research_identity(*, source_family: Any, notice_number: Any, procurement_id: Any) -> ResearchIdentity:
    """Resolve identity by normalized notice within an audited source family."""
    family = normalize_source_family(source_family)
    notice = _normalize_notice_number(notice_number)
    identity_part = notice or f"procurement_id:{int(procurement_id)}"
    return ResearchIdentity(
        source_family=family,
        notice_number=notice,
        procurement_id=int(procurement_id),
        key=f"{family}:{identity_part}",
    )


def canonical_identity_sql(alias: str = "q") -> str:
    """SQL fallback for queue rows created before identity context was persisted."""
    return (
        f"COALESCE({alias}.category_context->>'research_identity_key', "
        f"regexp_replace(regexp_replace(upper({alias}.source_table), "
        "'_(AWARDED|COMPLETED|COMMISSION_WORK|UNCLEAR|UNKNOWN)$', ''), "
        "'^REESTR_CONTRACT_', '') || ':' || "
        f"upper(regexp_replace(trim({alias}.contract_number), '\\s+', '', 'g')))"
    )


def research_disposition(
    rows: Sequence[Mapping[str, Any]],
    *,
    canonical_links_available: bool | None = None,
) -> str:
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
    if "NO_LINKS" in statuses:
        if canonical_links_available:
            return "RETRY_EXISTING_IDENTITY"
        return "DO_NOT_RETRY_NO_LINKS"
    if statuses.intersection({"FAILED", "PARTIAL"}):
        return "RETRY_EXISTING_IDENTITY"
    return "NEW_RESEARCH_ALLOWED"
