"""Wave-1 source corpus: identity, lifecycle, integrity, OKPD hierarchy helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from src.services.commercial_routing_v3.projection import (
    normalize_contract_number,
    resolve_lifecycle_identity,
)
from src.services.commercial_routing_v3.source_contour import resolve_source_contour
from src.services.commercial_routing_v3.source_lifecycle import (
    normalize_source_lifecycle_event,
)

PROCUREMENT_TABLES: Tuple[Tuple[str, str, str], ...] = (
    # table, customer_col, physical_stage label
    ("reestr_contract_44_fz", "customer", "OPEN"),
    ("reestr_contract_223_fz", "placer", "OPEN"),
    ("reestr_contract_44_fz_commission_work", "customer", "COMMISSION"),
    ("reestr_contract_223_fz_commission_work", "placer", "COMMISSION"),
    ("reestr_contract_44_fz_awarded", "customer", "AWARDED"),
    ("reestr_contract_223_fz_awarded", "placer", "AWARDED"),
)

PLACEHOLDERS = frozenset(
    {"", "(без названия)", "без названия", "не указано", "н/д", "null"}
)

INTEGRITY_VALID = "SOURCE_VALID"
INTEGRITY_OKPD_MISSING = "SOURCE_OKPD_MISSING"
INTEGRITY_PLACEHOLDER = "SOURCE_PLACEHOLDER"
INTEGRITY_IDENTITY_CONFLICT = "SOURCE_IDENTITY_CONFLICT"
INTEGRITY_PROJECTION_ERROR = "SOURCE_PROJECTION_ERROR"
INTEGRITY_OTHER = "OTHER_SOURCE_INTEGRITY_ERROR"

PRE_ROUTING_READY = "PRE_ROUTING_READY"
PRE_VALID_PREPARED = "SOURCE_VALID_PREPARED"
PRE_NO_OKPD = "NO_OKPD_CONTEXT"
PRE_INTEGRITY_INCOMPLETE = "SOURCE_INTEGRITY_INCOMPLETE"


def law_of(table: str) -> str:
    return "223_FZ" if "223" in (table or "").lower() else "44_FZ"


def is_placeholder(title: Any) -> bool:
    return str(title or "").strip().lower() in PLACEHOLDERS


@dataclass
class CorpusRow:
    identity_key: str
    source_contour: str
    contract_number: Optional[str]
    source_table: str
    source_id: int
    law_type: str
    physical_stage: str
    normalized_lifecycle: str
    auction_name: str
    okpd_id: Optional[int]
    okpd_code: Optional[str]
    okpd_name: Optional[str]
    end_date: Any = None
    source_created_at: Any = None
    source_updated_at: Any = None
    integrity_class: str = INTEGRITY_VALID
    pre_routing_state: str = PRE_VALID_PREPARED
    okpd_root: Optional[str] = None
    okpd_parent: Optional[str] = None
    okpd_hierarchy: List[str] = field(default_factory=list)
    prior_categories: List[str] = field(default_factory=list)
    prior_link_count: int = 0
    business_okpd_bucket: str = "OTHER"
    crm_procurement_id: Optional[int] = None
    discovery_class: str = "UNKNOWN"


def lifecycle_rank(lc: str) -> int:
    return {"OPEN": 1, "WAITING_SOURCE_OUTCOME": 2, "AWARDED": 3}.get(lc, 0)


def build_identity_key(table: str, source_id: int, contract_number: Any) -> Tuple[str, Optional[str], str]:
    ident = resolve_lifecycle_identity(
        source_table=table,
        source_id=source_id,
        contract_number=contract_number,
    )
    cn = normalize_contract_number(contract_number)
    key = "|".join(str(x) for x in ident.key())
    return key, cn, ident.source_contour.value


def normalize_lifecycle(table: str, end_date: Any, as_of: Optional[date] = None) -> str:
    return normalize_source_lifecycle_event(
        source_table=table,
        end_date=end_date,
        as_of=as_of or date.today(),
    ).value


def classify_integrity(
    *,
    auction_name: Any,
    okpd_code: Optional[str],
    source_id: Any,
    contract_number: Optional[str],
    identity_conflict: bool,
) -> str:
    if identity_conflict:
        return INTEGRITY_IDENTITY_CONFLICT
    if source_id is None and not contract_number:
        return INTEGRITY_PROJECTION_ERROR
    if is_placeholder(auction_name):
        return INTEGRITY_PLACEHOLDER
    if not (okpd_code or "").strip():
        return INTEGRITY_OKPD_MISSING
    return INTEGRITY_VALID


def business_okpd_bucket(okpd_code: Optional[str], integrity: str) -> str:
    if integrity == INTEGRITY_OKPD_MISSING or not (okpd_code or "").strip():
        return "SOURCE_OKPD_MISSING"
    code = okpd_code.strip()
    if code.startswith(("41.", "42.", "43.")):
        return "CONSTRUCTION"
    if code.startswith(("71.", "74.")):
        return "DESIGN_PIR"
    if code.startswith("26.2"):
        return "COMPUTERS"
    if code.startswith("27.40"):
        return "LIGHTING"
    return "OTHER"


def pre_routing_state(integrity: str, prior_count: int, okpd_code: Optional[str]) -> str:
    if integrity != INTEGRITY_VALID:
        if integrity == INTEGRITY_OKPD_MISSING:
            return PRE_NO_OKPD
        return PRE_INTEGRITY_INCOMPLETE
    if prior_count > 0:
        return PRE_ROUTING_READY
    if okpd_code:
        return PRE_VALID_PREPARED
    return PRE_NO_OKPD
