"""Дополнение карточек из реестра tender_monitor (если индекс устарел)."""
from collections import defaultdict
from typing import Dict, List, Optional

from loguru import logger

from src.services.object_models import ObjectViewItem
from src.services.tender_registry_query import fetch_registry_rows_by_ids


def _date_str(val) -> Optional[str]:
    if not val:
        return None
    return str(val)[:10]


def enrich_tender_items(tender_db, items: List[ObjectViewItem]) -> None:
    """Подтянуть даты, балансодержателя и победителя с сервера для видимых карточек."""
    if not tender_db or not items:
        return
    by_table: Dict[str, List[ObjectViewItem]] = defaultdict(list)
    for item in items:
        if (
            item.tender_id
            and item.registry_type
            and "nashdom" not in (item.sources or [])
        ):
            by_table[item.registry_type].append(item)

    for registry_type, table_items in by_table.items():
        ids = [i.tender_id for i in table_items if i.tender_id is not None]
        if not ids:
            continue
        try:
            rows = fetch_registry_rows_by_ids(tender_db, registry_type, ids)
        except Exception as exc:
            logger.warning(f"enrich_tender_items {registry_type}: {exc}")
            continue

        row_map = {int(r["tender_id"]): r for r in rows if r.get("tender_id") is not None}
        for item in table_items:
            row = row_map.get(item.tender_id)
            if not row:
                continue
            _apply_row(item, row)


def _apply_row(item: ObjectViewItem, row: dict) -> None:
    bh = (row.get("balance_holder") or "").strip()
    if bh:
        item.balance_holder = bh
    if row.get("organizer_name"):
        item.customer_name = row.get("organizer_name")
    if row.get("organizer_inn"):
        item.customer_inn = row.get("organizer_inn")
    if row.get("contractor_name"):
        item.contractor_name = row.get("contractor_name")
    if row.get("contractor_inn"):
        item.contractor_inn = row.get("contractor_inn")
    for field, key in (
        ("start_date", "start_date"),
        ("end_date", "end_date"),
        ("delivery_start_date", "delivery_start_date"),
        ("delivery_end_date", "delivery_end_date"),
    ):
        val = _date_str(row.get(key))
        if val:
            setattr(item, field, val)
