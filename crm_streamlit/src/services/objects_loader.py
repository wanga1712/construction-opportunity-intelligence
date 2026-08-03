"""Загрузка отобранных объектов: настройки superuser, экспертиза, совпадения в документах."""
import os
from typing import Dict, List, Optional, Set, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor
from loguru import logger

from modules.crm.analytics.object_classifier import classify_text
from modules.crm.analytics.tender_row_utils import query_dicts
from modules.crm.analytics.tender_superuser_settings import (
    TenderSuperuserSettings,
    TenderSuperuserSettingsLoader,
)
from modules.crm.repositories.tender_registry_constants import registry_label
from src.constants.object_quality import resolve_quality_tier
from src.services.object_models import ObjectViewItem
from src.services.objects_loader_nashdom import load_linked_nashdom, load_residential_nashdom
from src.services.tender_registry_query import (
    TENDER_TABLES,
    fetch_registry_rows_by_ids,
    fetch_registry_rows_by_numbers,
)

def _date_str(val) -> Optional[str]:
    if not val:
        return None
    return str(val)[:10]

def load_curated_objects(
    radar_db,
    tender_db,
) -> Tuple[List[ObjectViewItem], Optional[TenderSuperuserSettings], Dict[int, str]]:
    """
    Объекты по настройкам superuser (регион, ОКПД, стоп-слова).
    Не грузим весь NashDom — только связанные записи и отобранные закупки.
    """
    settings = TenderSuperuserSettingsLoader(tender_db).load() if tender_db else None
    region_names = _load_region_names(tender_db, settings)

    doc_index = _load_document_match_index(tender_db)
    expertise_by_key, expertise_by_number = _load_expertise_maps(tender_db)

    # Procurement: only tenders with confirmed interesting document matches.
    tender_keys: Set[Tuple[int, str]] = set(doc_index.keys())
    items: List[ObjectViewItem] = []
    seen_keys: Set[str] = set()

    for registry_type in TENDER_TABLES:
        table_keys = {k for k in tender_keys if k[1] == registry_type}
        if not table_keys:
            continue
        ids = [k[0] for k in table_keys]
        rows = fetch_registry_rows_by_ids(tender_db, registry_type, ids, settings=settings)
        for row in rows:
            tender_id = row["tender_id"]
            key = (tender_id, registry_type)
            doc = doc_index.get(key, {})
            contract_number = (row.get("contract_number") or "").strip()
            expertise_number = expertise_by_key.get(key)
            if not expertise_number and contract_number:
                expertise_number = expertise_by_number.get(contract_number)

            doc_matches = int(doc.get("doc_matches") or 0)
            customer_inn = row.get("organizer_inn")
            contractor_inn = row.get("contractor_inn")
            if not _include_tender_item(
                doc_matches=doc_matches,
                in_doc_index=key in doc_index,
            ):
                continue

            item_key = f"tender:{registry_type}:{tender_id}"
            if item_key in seen_keys:
                continue
            seen_keys.add(item_key)

            text = " ".join(filter(None, [row.get("auction_name"), row.get("delivery_address")]))
            segment = classify_text(text)
            # Keep classifier "other" as-other; do not force residential.
            tier = resolve_quality_tier(
                doc_matches=doc_matches,
                expertise_number=expertise_number,
                customer_inn=customer_inn,
                contractor_inn=contractor_inn,
            )
            info_flags = _build_info_flags(
                row, doc, expertise_number,
            )

            items.append(ObjectViewItem(
                key=item_key,
                name=row.get("auction_name") or "—",
                address=row.get("delivery_address") or row.get("delivery_region"),
                segment=segment,
                status=registry_label(registry_type),
                sources=[_source_from_registry(registry_type)],
                pd_number=expertise_number,
                expertise_number=expertise_number,
                contract_number=contract_number or None,
                region=row.get("region_name") or row.get("delivery_region"),
                region_id=row.get("region_id"),
                registry_type=registry_type,
                tender_id=tender_id,
                doc_matches=doc_matches,
                matched_files=int(doc.get("matched_files") or 0),
                matched_product_preview=list(doc.get("matched_product_preview") or []),
                matched_product_groups=set(doc.get("matched_product_groups") or set()),
                docs_volume_preview=doc.get("docs_volume_preview"),
                docs_preview_line=doc.get("docs_preview_line"),
                balance_holder=(row.get("balance_holder") or "").strip() or None,
                customer_name=row.get("organizer_name"),
                customer_inn=row.get("organizer_inn"),
                contractor_name=row.get("contractor_name"),
                contractor_inn=contractor_inn,
                start_date=_date_str(row.get("start_date")),
                end_date=_date_str(row.get("end_date")),
                delivery_start_date=_date_str(row.get("delivery_start_date")),
                delivery_end_date=_date_str(row.get("delivery_end_date")),
                quality_tier=tier,
                info_flags=info_flags,
                info_score=len(info_flags),
            ))

    nashdom_items = load_linked_nashdom(radar_db, items)
    for nd in nashdom_items:
        if nd.key not in seen_keys:
            seen_keys.add(nd.key)
            items.append(nd)

    residential_nashdom_items = load_residential_nashdom(radar_db)
    for nd in residential_nashdom_items:
        if nd.key not in seen_keys:
            seen_keys.add(nd.key)
            items.append(nd)

    from src.services.docs_match_preview import apply_match_previews

    apply_match_previews(tender_db, items)
    items.sort(key=lambda o: (-o.info_score, o.name or ""))
    return items, settings, region_names


def _include_tender_item(
    *,
    doc_matches: int,
    in_doc_index: bool,
) -> bool:
    """Закупочный контур: только подтверждённые совпадения в документах."""
    return int(doc_matches or 0) > 0 or bool(in_doc_index)


def _build_info_flags(row, doc: dict, expertise_number: Optional[str]) -> List[str]:
    flags: List[str] = []
    matches = int(doc.get("doc_matches") or 0)
    if matches > 0:
        flags.append(f"Док: {matches}")
    if expertise_number:
        flags.append(f"Эксп. {expertise_number}")
    if row.get("balance_holder"):
        flags.append("Балансодержатель")
    if row.get("organizer_inn"):
        flags.append("Организатор")
    if row.get("contractor_inn"):
        flags.append("Победитель")
    return flags


def _source_from_registry(registry_type: str) -> str:
    rt = (registry_type or "").lower()
    if "615" in rt:
        return "615pp"
    if "223" in rt:
        return "223fz"
    return "44fz"


def _load_region_names(tender_db, settings: Optional[TenderSuperuserSettings]) -> Dict[int, str]:
    if not tender_db or not settings or not settings.region_ids:
        return {}
    placeholders = ",".join(["%s"] * len(settings.region_ids))
    rows = query_dicts(
        tender_db,
        f"SELECT id, name FROM region WHERE id IN ({placeholders}) ORDER BY name",
        tuple(settings.region_ids),
    )
    return {int(r["id"]): r["name"] for r in rows if r.get("id") is not None}


def _load_document_match_index(tender_db) -> Dict[Tuple[int, str], dict]:
    if not tender_db:
        return {}
    rows = query_dicts(tender_db, """
        SELECT tender_id, registry_type,
               SUM(match_count) AS doc_matches,
               COUNT(DISTINCT id) AS matched_files
        FROM tender_document_matches
        WHERE is_interesting = TRUE
          AND (
            registry_type LIKE 'reestr_contract_44_fz%%'
            OR registry_type LIKE 'reestr_contract_223_fz%%'
            OR registry_type LIKE 'reestr_contract_615_pp%%'
          )
        GROUP BY tender_id, registry_type
    """)
    return {
        (int(r["tender_id"]), r["registry_type"]): r
        for r in rows
        if r.get("tender_id") is not None and r.get("registry_type")
    }


def _load_expertise_maps(
    tender_db,
) -> Tuple[Dict[Tuple[int, str], str], Dict[str, str]]:
    """Связки закупка ↔ номер положительного заключения (пакетно)."""
    by_key: Dict[Tuple[int, str], str] = {}
    by_number: Dict[str, str] = {}
    if not tender_db:
        return by_key, by_number
    cfg = tender_db.connection_manager.config
    db_name = os.getenv("EXPERTISE_DB_DATABASE", "expertise_registry")
    try:
        conn = psycopg2.connect(
            host=cfg.host,
            database=db_name,
            user=cfg.user,
            password=cfg.password,
            port=cfg.port,
            cursor_factory=RealDictCursor,
        )
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.tender_number, m.tender_table, e.expertise_number
                FROM expertise_tender_matches m
                JOIN expertise_conclusions e ON e.id = m.expertise_id
                WHERE COALESCE(m.is_relevant, FALSE) = TRUE
                  AND e.expertise_result_type ILIKE '%%Положитель%%'
                  AND m.tender_number IS NOT NULL
                  AND m.tender_table IS NOT NULL
            """)
            rows = [dict(r) for r in cur.fetchall()]
        conn.close()
    except Exception as exc:
        logger.warning(f"expertise_registry недоступна: {exc}")
        return by_key, by_number

    by_table: Dict[str, Dict[str, str]] = {}
    for row in rows:
        number = (row.get("tender_number") or "").strip()
        table = (row.get("tender_table") or "").strip()
        exp_no = (row.get("expertise_number") or "").strip()
        if not number or not table or not exp_no:
            continue
        by_number[number] = exp_no
        if table in TENDER_TABLES:
            by_table.setdefault(table, {})[number] = exp_no

    for table, number_map in by_table.items():
        numbers = list(number_map.keys())
        if not numbers:
            continue
        found = fetch_registry_rows_by_numbers(tender_db, (table,), numbers)
        for cn, row in found.items():
            exp_no = number_map.get(cn)
            tender_id = row.get("current_tender_id")
            if exp_no and tender_id is not None:
                by_key[(int(tender_id), table)] = exp_no
    return by_key, by_number


