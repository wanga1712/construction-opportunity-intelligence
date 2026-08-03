"""Преобразование строк crm_objects_index ↔ ObjectViewItem."""
import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from modules.crm.repositories.objects_index_repository import item_to_index_row
from src.services.object_models import ObjectViewItem


def _row_date(val) -> Optional[str]:
    if not val:
        return None
    if isinstance(val, (date, datetime)):
        return val.isoformat()[:10]
    return str(val)[:10]


def index_row_to_item(row: Dict[str, Any]) -> ObjectViewItem:
    flags = row.get("info_flags") or []
    if isinstance(flags, str):
        flags = json.loads(flags)
    sources = row.get("source_codes") or []
    if isinstance(sources, str):
        sources = json.loads(sources)
    return ObjectViewItem(
        key=row["object_key"],
        name=row.get("name") or "—",
        address=row.get("address"),
        segment=row.get("segment") or "other",
        status=row.get("status"),
        sources=list(sources),
        pd_number=row.get("pd_number"),
        expertise_number=row.get("expertise_number"),
        contract_number=row.get("contract_number"),
        region=row.get("region_name"),
        region_id=row.get("region_id"),
        registry_type=row.get("registry_type"),
        tender_id=row.get("tender_id"),
        domrf_object_id=row.get("domrf_object_id"),
        doc_matches=int(row.get("doc_matches") or 0),
        matched_files=int(row.get("matched_files") or 0),
        customer_name=row.get("customer_name"),
        customer_inn=row.get("customer_inn"),
        contractor_name=row.get("contractor_name"),
        contractor_inn=row.get("contractor_inn"),
        balance_holder=row.get("balance_holder"),
        start_date=_row_date(row.get("start_date")),
        end_date=_row_date(row.get("end_date")),
        delivery_start_date=_row_date(row.get("delivery_start_date")),
        delivery_end_date=_row_date(row.get("delivery_end_date")),
        quality_tier=row.get("quality_tier") or "basic",
        info_flags=list(flags),
        info_score=int(row.get("info_score") or 0),
        search_text=row.get("search_text") or "",
    )


def items_to_index_rows(items: List[ObjectViewItem]) -> List[Dict[str, Any]]:
    return [item_to_index_row(item) for item in items]
