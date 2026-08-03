"""Runtime enrichment from expertise_registry.

The CRM index may be older than the procurement tables: tenders move between
active/commission/awarded tables, while the indexed ``registry_type + id`` stays
stale.  This module uses the stable expertise number and tender number links to
restore participants and dates without rebuilding the whole index on every UI
request.
"""
from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional

import psycopg2
from loguru import logger
from psycopg2.extras import RealDictCursor

from modules.crm.repositories.tender_registry_constants import registry_label
from src.services.object_lifecycle import is_awarded
from src.services.object_models import ObjectViewItem
from src.services.tender_registry_query import (
    TENDER_TABLES,
    fetch_registry_rows_by_numbers,
)


def enrich_objects_from_expertise(
    tender_db,
    items: Iterable[ObjectViewItem],
    *,
    max_items: int = 80,
) -> None:
    """Fill planner/developer and recover current tender dates by expertise link."""
    raw_items = [i for i in items if "nashdom" not in (i.sources or [])]
    item_list = [i for i in raw_items if _needs_enrichment(i)]
    if len(item_list) > max_items:
        item_list = sorted(item_list, key=_item_priority_for_enrichment, reverse=True)[:max_items]
    if not tender_db or not item_list:
        return

    by_exp: Dict[str, List[ObjectViewItem]] = {}
    for item in item_list:
        exp = _expertise_number(item)
        if exp:
            item.expertise_number = item.expertise_number or exp
            item.pd_number = item.pd_number or exp
            by_exp.setdefault(exp, []).append(item)
    if not by_exp:
        return

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
            placeholders = ",".join(["%s"] * len(by_exp))
            cur.execute(
                f"""
                SELECT
                    e.expertise_number,
                    e.expertise_object_name_and_address,
                    e.developer_organization_info,
                    e.technical_customer_organization_info,
                    e.planner_organization_info,
                    m.tender_table,
                    m.tender_id,
                    m.tender_number,
                    m.tender_name,
                    m.tender_price,
                    m.tender_start_date,
                    COALESCE(m.is_relevant, false) AS is_relevant,
                    m.match_score,
                    m.created_at
                FROM expertise_conclusions e
                LEFT JOIN LATERAL (
                    SELECT *
                    FROM expertise_tender_matches
                    WHERE expertise_id = e.id
                    ORDER BY
                        COALESCE(is_relevant, false) DESC,
                        created_at DESC NULLS LAST
                    LIMIT 12
                ) m ON true
                WHERE e.expertise_number IN ({placeholders})
                ORDER BY
                    e.expertise_number,
                    COALESCE(m.is_relevant, false) DESC,
                    m.created_at DESC NULLS LAST
                """,
                tuple(by_exp.keys()),
            )
            rows = [dict(r) for r in cur.fetchall()]
        conn.close()
    except Exception as exc:
        logger.warning(f"enrich_objects_from_expertise: {exc}")
        return

    rows_by_exp: Dict[str, List[dict]] = {}
    tender_numbers: set[str] = set()
    for row in rows:
        exp = (row.get("expertise_number") or "").strip()
        if not exp:
            continue
        rows_by_exp.setdefault(exp, []).append(row)
        num = (row.get("tender_number") or "").strip()
        if num:
            tender_numbers.add(num)

    tender_rows = _load_current_tenders_by_number(tender_db, sorted(tender_numbers))

    for exp, exp_items in by_exp.items():
        candidates = rows_by_exp.get(exp) or []
        if not candidates:
            continue
        for item in exp_items:
            best = _best_row_for_item(item, candidates)
            if not best:
                continue
            _apply_expertise_participants(item, best)
            number = (best.get("tender_number") or "").strip()
            current = tender_rows.get(number) if number else None
            _apply_tender_link(item, best, current)


def _needs_enrichment(item: ObjectViewItem) -> bool:
    return (
        bool(_expertise_number(item))
        and (
            not item.expertise_planner
            or not item.start_date
            or (not is_awarded(item) and not item.end_date)
            or not item.contract_number
        )
    )


def _item_priority_for_enrichment(item: ObjectViewItem) -> int:
    score = 0
    if not is_awarded(item):
        score += 50
    if item.doc_matches or item.matched_files:
        score += 30
    if not item.start_date or not item.end_date:
        score += 20
    score += min(int(item.info_score or 0), 20)
    return score


def _expertise_number(item: ObjectViewItem) -> Optional[str]:
    for value in (item.expertise_number, item.pd_number):
        found = _extract_expertise_number(value)
        if found:
            return found
    for flag in item.info_flags or []:
        found = _extract_expertise_number(flag)
        if found:
            return found
    return None


def _extract_expertise_number(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    match = re.search(r"\b\d{2}-\d-\d-\d-\d{5,}-\d{4}\b", str(value))
    return match.group(0) if match else None


def _norm(value: Optional[str]) -> str:
    text = (value or "").lower()
    text = re.sub(r"[^0-9a-zа-яё]+", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _similar(a: Optional[str], b: Optional[str]) -> float:
    aa, bb = _norm(a), _norm(b)
    if not aa or not bb:
        return 0.0
    if aa in bb or bb in aa:
        return 0.92
    return SequenceMatcher(None, aa[:500], bb[:500]).ratio()


def _best_row_for_item(item: ObjectViewItem, rows: List[dict]) -> Optional[dict]:
    def score(row: dict) -> float:
        s = 0.0
        if row.get("is_relevant"):
            s += 20.0
        if item.contract_number and row.get("tender_number") == item.contract_number:
            s += 100.0
        if item.tender_id and row.get("tender_id") and int(row["tender_id"]) == int(item.tender_id):
            s += 45.0
        if item.registry_type and row.get("tender_table") == item.registry_type:
            s += 20.0
        sim_name = _similar(item.name, row.get("tender_name"))
        sim_obj = _similar(item.name, row.get("expertise_object_name_and_address"))
        s += max(sim_name, sim_obj) * 55.0
        if not is_awarded(item) and (row.get("tender_table") or "") in (
            "reestr_contract_44_fz",
            "reestr_contract_44_fz_commission_work",
        ):
            s += 15.0
        return s

    ranked = sorted(rows, key=score, reverse=True)
    if not ranked:
        return None
    return ranked[0]


def _load_current_tenders_by_number(tender_db, numbers: List[str]) -> Dict[str, dict]:
    if not numbers:
        return {}
    try:
        return fetch_registry_rows_by_numbers(tender_db, TENDER_TABLES, numbers)
    except Exception as exc:
        logger.warning(f"_load_current_tenders_by_number: {exc}")
        return {}


def _date_str(value) -> Optional[str]:
    if not value:
        return None
    return str(value)[:10]


def _clean_org(value: Optional[str], limit: int = 220) -> Optional[str]:
    if not value:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:limit].rstrip()


def _apply_expertise_participants(item: ObjectViewItem, row: dict) -> None:
    item.expertise_developer = _clean_org(row.get("developer_organization_info")) or item.expertise_developer
    item.expertise_technical_customer = (
        _clean_org(row.get("technical_customer_organization_info"))
        or item.expertise_technical_customer
    )
    item.expertise_planner = _clean_org(row.get("planner_organization_info")) or item.expertise_planner


def _apply_tender_link(item: ObjectViewItem, match_row: dict, current_row: Optional[dict]) -> None:
    num = (match_row.get("tender_number") or "").strip()
    if num:
        item.matched_tender_number = num
        item.contract_number = item.contract_number or num
    if match_row.get("tender_table"):
        item.matched_tender_table = match_row.get("tender_table")
    if match_row.get("tender_id") is not None:
        item.matched_tender_id = int(match_row["tender_id"])

    row = current_row or {}
    if row.get("current_table"):
        item.registry_type = row.get("current_table")
        item.status = registry_label(item.registry_type)
    if row.get("current_tender_id"):
        item.tender_id = int(row["current_tender_id"])
    if row.get("auction_name"):
        item.name = row.get("auction_name")
    if row.get("balance_holder"):
        item.balance_holder = (row.get("balance_holder") or "").strip() or item.balance_holder
    if row.get("organizer_name"):
        item.customer_name = row.get("organizer_name")
    if row.get("organizer_inn"):
        item.customer_inn = row.get("organizer_inn")
    if row.get("contractor_name"):
        item.contractor_name = row.get("contractor_name")
    if row.get("contractor_inn"):
        item.contractor_inn = row.get("contractor_inn")

    for attr in ("start_date", "end_date", "delivery_start_date", "delivery_end_date"):
        val = _date_str(row.get(attr))
        if val:
            setattr(item, attr, val)
    if not item.start_date:
        item.start_date = _date_str(match_row.get("tender_start_date"))
