"""Shared object lifecycle predicates: awarded, sales window, ISO dates.

Single owner for rules used by ObjectsService, leads bridge, AI, waterproofing.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from src.services.object_models import ObjectViewItem

DEFAULT_SALES_WINDOW_DAYS = 90
# После end_date открытая закупка считается протухшей для вкладки «Не разыграны».
OPEN_TENDER_END_GRACE_DAYS = 0


def sales_window_end_raw(item: ObjectViewItem) -> Optional[str]:
    """Дата, по которой объект ещё в активном продажном окне."""
    if is_awarded(item):
        return item.delivery_end_date or item.end_date
    # Для неразыгранных важен срок торгов, а не плановая поставка из ТЗ.
    return item.end_date or item.delivery_end_date


def sales_window_days_left(item: ObjectViewItem) -> Optional[int]:
    return date_days_left(sales_window_end_raw(item))


def date_iso(val) -> Optional[str]:
    """Normalize a date-like value to YYYY-MM-DD for storage/index."""
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val.date().isoformat()
    if isinstance(val, date):
        return val.isoformat()
    text = str(val).strip()
    if len(text) >= 10 and text[4:5] == "-":
        return text[:10]
    return text[:10] if text else None


def date_days_left(raw: object) -> Optional[int]:
    if not raw:
        return None
    try:
        return (date.fromisoformat(str(raw)[:10]) - date.today()).days
    except Exception:
        return None


def delivery_days_left(item: ObjectViewItem) -> Optional[int]:
    """Days before execution/supply end (commercial sales window)."""
    return date_days_left(item.delivery_end_date)


def tender_days_left(item: ObjectViewItem) -> Optional[int]:
    """Days before bid/application end (not the supply window)."""
    return date_days_left(item.end_date)


def days_left(item: ObjectViewItem) -> Optional[int]:
    """Days left in sales window (awarded → delivery, open → tender end)."""
    return sales_window_days_left(item)


def is_awarded_registry(registry_type: Optional[str]) -> bool:
    """Registry-only awarded/completed (card layout: show winner/delivery)."""
    if not registry_type:
        return False
    rt = registry_type.lower()
    return "awarded" in rt or "completed" in rt


def is_awarded(item: ObjectViewItem) -> bool:
    """Full awarded detection: registry type + status text."""
    if is_awarded_registry(item.registry_type):
        return True
    text = f"{item.status or ''}".lower()
    return (
        "разыгран" in text
        or "заверш" in text
        or "исполнен" in text
        or "контракт заключ" in text
    )


def has_sales_window(
    item: ObjectViewItem,
    *,
    min_days_left: int = DEFAULT_SALES_WINDOW_DAYS,
) -> bool:
    raw = sales_window_end_raw(item)
    if not raw:
        return False
    try:
        end = date.fromisoformat(str(raw)[:10])
    except Exception:
        return False
    return end >= date.today() + timedelta(days=min_days_left)


def is_stale_open_tender(
    item: ObjectViewItem,
    *,
    grace_days: int = OPEN_TENDER_END_GRACE_DAYS,
) -> bool:
    """True when bid period ended and tender is still not awarded."""
    if is_awarded(item):
        return False
    left = tender_days_left(item)
    if left is None:
        return False
    return left < -grace_days


def is_lost_for_sales_window(
    item: ObjectViewItem,
    *,
    min_days_left: int = DEFAULT_SALES_WINDOW_DAYS,
    min_days: Optional[int] = None,
) -> bool:
    """True when object is too late for active material sales."""
    if min_days is not None:
        min_days_left = min_days
    if is_stale_open_tender(item):
        return True
    left = sales_window_days_left(item)
    if left is None:
        return False
    return left < min_days_left


def min_delivery_end_date(min_days: int = DEFAULT_SALES_WINDOW_DAYS) -> date:
    return date.today() + timedelta(days=min_days)
