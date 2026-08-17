"""Null-safe dirty-check for 44-FZ RGK registry rows."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Optional, Sequence

DIRTY_FIELDS: Sequence[str] = (
    "final_price",
    "contractor_id",
    "delivery_start_date",
    "delivery_end_date",
    "auction_name",
    "okpd_id",
)


def _as_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _as_date_text(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    return text[:10]


def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_field(name: str, value: Any) -> Any:
    if name in ("delivery_start_date", "delivery_end_date"):
        return _as_date_text(value)
    if name == "final_price":
        return _as_decimal(value)
    if name in ("contractor_id", "okpd_id"):
        return _as_int(value)
    if name == "auction_name":
        if value is None:
            return None
        text = str(value).strip()
        return text or None
    return value


def incoming_overrides(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> dict[str, Any]:
    """Fields the current updater would write: non-null incoming only."""
    payload: dict[str, Any] = {}
    for key in DIRTY_FIELDS:
        raw = incoming.get(key)
        if raw is None or raw == "":
            continue
        payload[key] = normalize_field(key, raw)
    return payload


def changed_fields(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> list[str]:
    changed: list[str] = []
    for key, new_value in incoming_overrides(existing, incoming).items():
        old_value = normalize_field(key, existing.get(key))
        if old_value != new_value:
            changed.append(key)
    return changed


def row_is_dirty(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> bool:
    return bool(changed_fields(existing, incoming))


def count_redundant(pairs: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]]) -> int:
    return sum(0 if row_is_dirty(old, new) else 1 for old, new in pairs)
