"""Полная загрузка объекта из tender_monitor / expertise / NashDom."""
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from loguru import logger

from modules.crm.repositories.tender_registry_constants import registry_label
from modules.crm.repositories.tender_repository import TenderDetailRepository
from src.services.expertise_enrich import enrich_objects_from_expertise
from src.services.object_enrich import enrich_tender_items
from src.services.object_models import ObjectViewItem
from src.services.tender_registry_query import fetch_registry_rows_by_ids


@dataclass
class ObjectDetailData:
    """Все известные данные по объекту."""
    item: ObjectViewItem
    tender_link: Optional[str] = None
    contract_number: Optional[str] = None
    initial_price: Optional[float] = None
    final_price: Optional[float] = None
    okpd_code: Optional[str] = None
    okpd_name: Optional[str] = None
    platform_name: Optional[str] = None
    platform_url: Optional[str] = None
    delivery_region: Optional[str] = None
    match_files: List[Dict[str, Any]] = field(default_factory=list)
    documents: List[Dict[str, Any]] = field(default_factory=list)
    expertise_rows: List[Dict[str, Any]] = field(default_factory=list)
    nashdom_rows: List[Dict[str, Any]] = field(default_factory=list)


def load_object_detail(
    item: ObjectViewItem,
    *,
    tender_db,
    radar_db,
) -> ObjectDetailData:
    """Живая загрузка из БД — не зависит от индекса CRM."""
    enrich_tender_items(tender_db, [item])
    enrich_objects_from_expertise(tender_db, [item])
    detail = ObjectDetailData(item=item)

    if item.tender_id and item.registry_type and "nashdom" not in item.sources:
        _load_tender_row(detail, tender_db)
        _load_matches_and_docs(detail, tender_db)
        _load_expertise(detail, tender_db)

    if item.domrf_object_id and radar_db:
        _load_nashdom(detail, radar_db)
    elif item.pd_number and radar_db:
        _load_nashdom_by_pd(detail, radar_db)

    return detail


def _load_tender_row(detail: ObjectDetailData, tender_db) -> None:
    item = detail.item
    registry_type = item.registry_type
    tender_id = item.tender_id
    rows = fetch_registry_rows_by_ids(
        tender_db, registry_type, [tender_id], mode="detail",
    )
    if not rows:
        return
    row = rows[0]
    item.name = row.get("auction_name") or item.name
    item.address = row.get("delivery_address") or item.address
    item.region = row.get("region_name") or row.get("delivery_region") or item.region
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
    for attr, key in (
        ("start_date", "start_date"), ("end_date", "end_date"),
        ("delivery_start_date", "delivery_start_date"),
        ("delivery_end_date", "delivery_end_date"),
    ):
        if row.get(key):
            setattr(item, attr, str(row[key])[:10])

    detail.tender_link = row.get("tender_link")
    detail.contract_number = row.get("contract_number")
    detail.delivery_region = row.get("delivery_region")
    detail.initial_price = _float(row.get("initial_price"))
    detail.final_price = _float(row.get("final_price"))
    main = row.get("okpd_main") or ""
    sub = row.get("okpd_sub") or ""
    detail.okpd_code = f"{main}.{sub}".strip(".") if main or sub else None
    detail.okpd_name = row.get("okpd_name")
    detail.platform_name = row.get("platform_name")
    detail.platform_url = row.get("platform_url")
    if not item.status:
        item.status = registry_label(registry_type)


def _load_matches_and_docs(detail: ObjectDetailData, tender_db) -> None:
    item = detail.item
    if not item.tender_id or not item.registry_type:
        return
    cfg = tender_db.connection_manager.config
    repo = TenderDetailRepository(
        cfg.host, cfg.database, cfg.user, cfg.password, cfg.port,
    )
    files = repo.get_match_files(item.tender_id, item.registry_type)
    detail.match_files = []
    for f in files:
        raw_details = repo.get_match_details(f.match_id)
        detail.match_files.append({
            "match_id": f.match_id,
            "file_name": f.file_name,
            "match_count": f.match_count,
            "match_percentage": f.match_percentage,
            "yandex_path": f.yandex_path,
            "folder_name": getattr(f, "folder_name", None),
            "details": [
                {
                    "product_name": d.product_name,
                    "score": d.score,
                    "keywords": list(d.matched_keywords or []),
                    "text": d.matched_display_text or "",
                    "source_file": d.source_file,
                    "sheet_name": d.sheet_name,
                    "cell_address": d.cell_address,
                    "line_number": d.line_number,
                }
                for d in raw_details
            ],
        })
    docs = repo.get_documents(item.tender_id, item.registry_type)
    detail.documents = [
        {"doc_id": d.doc_id, "file_name": d.file_name, "url": d.url}
        for d in docs
    ]
    item.doc_matches = sum(f["match_count"] for f in detail.match_files)
    item.matched_files = len(detail.match_files)


def _load_expertise(detail: ObjectDetailData, tender_db) -> None:
    item = detail.item
    cfg = tender_db.connection_manager.config
    db_name = os.getenv("EXPERTISE_DB_DATABASE", "expertise_registry")
    try:
        conn = psycopg2.connect(
            host=cfg.host, database=db_name, user=cfg.user,
            password=cfg.password, port=cfg.port,
            cursor_factory=RealDictCursor,
        )
        with conn.cursor() as cur:
            if item.expertise_number:
                cur.execute(
                    """
                    SELECT expertise_number, expertise_result_type, expertise_date
                    FROM expertise_conclusions
                    WHERE expertise_number = %s
                    LIMIT 3
                    """,
                    (item.expertise_number,),
                )
            elif item.contract_number:
                cur.execute(
                    """
                    SELECT e.expertise_number, e.expertise_result_type, e.expertise_date
                    FROM expertise_tender_matches m
                    JOIN expertise_conclusions e ON e.id = m.expertise_id
                    WHERE m.tender_number = %s
                    LIMIT 3
                    """,
                    (item.contract_number,),
                )
            else:
                conn.close()
                return
            detail.expertise_rows = [dict(r) for r in cur.fetchall()]
        conn.close()
    except Exception as exc:
        logger.warning(f"_load_expertise: {exc}")


def _load_nashdom(detail: ObjectDetailData, radar_db) -> None:
    oid = detail.item.domrf_object_id
    if not oid:
        return
    try:
        rows = radar_db.execute_query("""
            SELECT m.domrf_object_id, m.name, m.address_text, m.status_name,
                   o.pd_number, o.region_name
            FROM mart_msk_pipeline_objects m
            JOIN msk_object o USING (domrf_object_id)
            WHERE m.domrf_object_id = %s
        """, (oid,))
        detail.nashdom_rows = rows or []
    except Exception as exc:
        logger.warning(f"_load_nashdom: {exc}")


def _load_nashdom_by_pd(detail: ObjectDetailData, radar_db) -> None:
    pd = detail.item.pd_number or detail.item.expertise_number
    if not pd:
        return
    try:
        rows = radar_db.execute_query("""
            SELECT m.domrf_object_id, m.name, m.address_text, m.status_name,
                   o.pd_number, o.region_name
            FROM mart_msk_pipeline_objects m
            JOIN msk_object o USING (domrf_object_id)
            WHERE o.pd_number = %s
        """, (pd,))
        detail.nashdom_rows = rows or []
    except Exception as exc:
        logger.warning(f"_load_nashdom_by_pd: {exc}")


def _float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
