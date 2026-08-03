"""NashDom portions of the curated objects loader."""
from __future__ import annotations

import os
from typing import List, Set

from loguru import logger

from modules.crm.analytics.object_classifier import classify_text
from src.services.object_models import ObjectViewItem


def load_linked_nashdom(radar_db, tender_items: List[ObjectViewItem]) -> List[ObjectViewItem]:
    """Load only NashDom entries linked by PD/expertise number."""
    if not radar_db:
        return []
    pd_numbers: Set[str] = {
        value.strip()
        for item in tender_items
        for value in (item.pd_number, item.expertise_number)
        if value and value.strip()
    }
    if not pd_numbers:
        return []
    try:
        rows = radar_db.execute_query("""
            SELECT m.domrf_object_id, m.name, m.address_text, m.status_name,
                   o.pd_number, o.region_name
            FROM mart_msk_pipeline_objects m
            JOIN msk_object o USING (domrf_object_id)
            WHERE o.pd_number = ANY(%s) AND m.status_name IN ('Строится', 'Сдан')
        """, (list(pd_numbers),))
    except Exception as exc:
        logger.error(f"load_linked_nashdom: {exc}")
        return []
    result: List[ObjectViewItem] = []
    for row in rows:
        segment = classify_text(" ".join(filter(None, [row.get("name"), row.get("address_text")])))
        flags = ["NashDom"] + ([f"ПД {row['pd_number']}"] if row.get("pd_number") else [])
        result.append(ObjectViewItem(
            key=f"nashdom:{row['domrf_object_id']}", name=row.get("name") or "—",
            address=row.get("address_text"), segment="residential" if segment == "other" else segment,
            status=row.get("status_name"), sources=["nashdom"], pd_number=row.get("pd_number"),
            domrf_object_id=row.get("domrf_object_id"), region=row.get("region_name"),
            quality_tier="participants" if row.get("pd_number") else "basic",
            info_flags=flags, info_score=len(flags),
        ))
    return result


def load_residential_nashdom(radar_db) -> List[ObjectViewItem]:
    """Load the broad residential NashDom layer independently of tenders."""
    if not radar_db:
        return []
    try:
        limit = max(0, min(int(os.getenv("CRM_NASHDOM_RESIDENTIAL_LIMIT", "1000")), 10000))
    except ValueError:
        limit = 1000
    if not limit:
        return []
    try:
        rows = radar_db.execute_query("""
            SELECT m.domrf_object_id, m.name, m.address_text, m.status_name,
                   m.floors_underground, m.underground_parking_flag, m.finish_type,
                   m.finishing_stage_candidate, m.waterproofing_stage_candidate, m.parking_candidate,
                   o.pd_number, o.rns_number, o.region_name, o.keys_issue_from, o.keys_issue_to
            FROM mart_msk_pipeline_objects m JOIN msk_object o USING (domrf_object_id)
            WHERE m.status_name IN ('Строится', 'Сдан')
            ORDER BY m.status_name = 'Строится' DESC, m.finishing_stage_candidate DESC NULLS LAST,
                     m.parking_candidate DESC NULLS LAST, m.waterproofing_stage_candidate DESC NULLS LAST, m.name
            LIMIT %s
        """, (limit,))
    except Exception as exc:
        logger.error(f"load_residential_nashdom: {exc}")
        return []
    result: List[ObjectViewItem] = []
    for row in rows:
        flags = ["NashDom"]
        for flag, condition in (
            (row.get("status_name"), row.get("status_name")), (f"ПД {row['pd_number']}", row.get("pd_number")),
            ("РНС", row.get("rns_number")), ("Отделка", row.get("finishing_stage_candidate")),
            ("Паркинг", row.get("parking_candidate") or row.get("underground_parking_flag")),
            (f"Подз. {row['floors_underground']}", row.get("floors_underground")),
        ):
            if condition:
                flags.append(str(flag))
        search = [row.get(k) for k in ("name", "address_text", "region_name", "pd_number", "rns_number", "finish_type")]
        result.append(ObjectViewItem(
            key=f"nashdom:{row['domrf_object_id']}", name=row.get("name") or "Жилой объект NashDom",
            address=row.get("address_text"), segment="residential", status=row.get("status_name"),
            sources=["nashdom"], pd_number=row.get("pd_number"), domrf_object_id=row.get("domrf_object_id"),
            region=row.get("region_name"), start_date=_date_str(row.get("keys_issue_from")),
            end_date=_date_str(row.get("keys_issue_to")),
            quality_tier="participants" if row.get("pd_number") or row.get("rns_number") else "basic",
            info_flags=flags, info_score=len(flags),
            search_text=" ".join(str(value) for value in search if value),
        ))
    return result


def _date_str(value):
    return str(value)[:10] if value else None
