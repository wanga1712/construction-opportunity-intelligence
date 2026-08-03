"""Early opportunity radar: positive expertise conclusions before material hits."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from modules.crm.analytics.tender_row_utils import query_dicts
from src.constants.product_groups import PRODUCT_GROUP_OPTIONS, detect_product_groups_from_text, product_group_labels


AVERAGE_DAYS_TO_TENDER = int(os.getenv("RADAR_EXPERTISE_TO_TENDER_DAYS", "240"))


@dataclass
class RadarFilters:
    region_query: str = ""
    only_without_tender: bool = False
    product_group: str = "all"
    horizon_days: int = 365
    limit: int = 200


def _expertise_connection_from_tender_db(tender_db):
    cfg = tender_db.connection_manager.config
    db_name = os.getenv("EXPERTISE_DB_DATABASE", "expertise_registry")
    return psycopg2.connect(
        host=cfg.host,
        database=db_name,
        user=cfg.user,
        password=cfg.password,
        port=cfg.port,
        cursor_factory=RealDictCursor,
    )


def fetch_expertise_radar(tender_db, filters: RadarFilters) -> list[dict]:
    """Load positive expertise conclusions and forecast likely tender timing."""
    if not tender_db:
        return []

    since = date.today() - timedelta(days=max(filters.horizon_days, AVERAGE_DAYS_TO_TENDER))
    clauses = [
        "e.expertise_result_type ILIKE '%%Положитель%%'",
        "COALESCE(e.expertise_date, e.expertise_conclusion_date) >= %s",
    ]
    params: list = [since]

    if filters.region_query.strip():
        q = f"%{filters.region_query.strip()}%"
        clauses.append(
            "("
            "e.expertise_object_name_and_address ILIKE %s OR "
            "e.subject_rf ILIKE %s OR "
            "e.developer_organization_info ILIKE %s OR "
            "e.technical_customer_organization_info ILIKE %s OR "
            "e.planner_organization_info ILIKE %s"
            ")"
        )
        params.extend([q, q, q, q, q])

    if filters.only_without_tender:
        clauses.append("NOT EXISTS (SELECT 1 FROM expertise_tender_matches m WHERE m.expertise_id = e.id)")

    where = " AND ".join(clauses)
    params.append(filters.limit)

    sql = f"""
    SELECT
        e.id,
        e.expertise_number,
        e.expertise_result_type,
        COALESCE(e.expertise_date, e.expertise_conclusion_date) AS expertise_date,
        e.expertise_conclusion_date,
        e.subject_rf,
        e.subject_rf_code,
        e.expertise_object_name_and_address AS object_name,
        e.expertise_organization_info,
        e.developer_organization_info,
        e.technical_customer_organization_info,
        e.planner_organization_info,
        e.work_type,
        e.segment,
        e.segment_keywords,
        (
            SELECT COUNT(*)
            FROM expertise_tender_matches m
            WHERE m.expertise_id = e.id
        ) AS tender_match_count
    FROM expertise_conclusions e
    WHERE {where}
    ORDER BY COALESCE(e.expertise_date, e.expertise_conclusion_date) DESC NULLS LAST, e.id DESC
    LIMIT %s
    """

    with _expertise_connection_from_tender_db(tender_db) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = [dict(r) for r in cur.fetchall()]

    doc_hits = _expertise_ids_with_doc_hits(tender_db, [int(r["id"]) for r in rows if r.get("id") is not None])

    out: list[dict] = []
    for row in rows:
        exp_id = int(row["id"]) if row.get("id") is not None else None
        # Already in procurement: expertise linked to tender with interesting matches.
        if exp_id is not None and exp_id in doc_hits:
            continue

        row["region_name"] = row.get("subject_rf") or _guess_region(row.get("object_name"))
        interest_text = " ".join(
            str(x or "")
            for x in (
                row.get("object_name"),
                row.get("work_type"),
                row.get("segment"),
                row.get("segment_keywords"),
                row.get("developer_organization_info"),
                row.get("technical_customer_organization_info"),
                row.get("planner_organization_info"),
            )
        )
        groups = detect_product_groups_from_text(interest_text)
        row["product_interest_codes"] = sorted(groups)
        row["product_interest_labels"] = product_group_labels(groups)

        if filters.product_group != "all" and filters.product_group not in groups:
            continue

        row.update(_forecast(row))
        tender_count = int(row.get("tender_match_count") or 0)
        if tender_count > 0:
            row["radar_phase"] = "tender_docs_pending"
            row["radar_priority"] = max(int(row.get("radar_priority") or 0), 88)
            row["source_label"] = "Экспертиза + закупка (ждём разбор документов)"
        out.append(row)
    return out


def _expertise_ids_with_doc_hits(tender_db, expertise_ids: list[int]) -> set[int]:
    """Expertise rows whose linked tender already has interesting document matches."""
    if not tender_db or not expertise_ids:
        return set()
    placeholders = ",".join(["%s"] * len(expertise_ids))
    try:
        with _expertise_connection_from_tender_db(tender_db) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT m.expertise_id, m.tender_number, m.tender_table
                    FROM expertise_tender_matches m
                    WHERE m.expertise_id IN ({placeholders})
                      AND COALESCE(m.is_relevant, FALSE) = TRUE
                      AND m.tender_number IS NOT NULL
                      AND m.tender_table IS NOT NULL
                    """,
                    tuple(expertise_ids),
                )
                links = [dict(r) for r in cur.fetchall()]
    except Exception:
        return set()

    if not links:
        return set()

    by_table: dict[str, list[str]] = {}
    for link in links:
        table = (link.get("tender_table") or "").strip()
        number = (link.get("tender_number") or "").strip()
        if table and number:
            by_table.setdefault(table, []).append(number)

    numbers_with_hits: set[tuple[str, str]] = set()
    for table, numbers in by_table.items():
        uniq = sorted(set(numbers))
        ph = ",".join(["%s"] * len(uniq))
        try:
            rows = query_dicts(
                tender_db,
                f"""
                SELECT DISTINCT r.contract_number
                FROM {table} r
                JOIN tender_document_matches m
                  ON m.tender_id = r.current_tender_id
                 AND m.registry_type = %s
                WHERE r.contract_number IN ({ph})
                  AND m.is_interesting = TRUE
                  AND COALESCE(m.match_count, 0) > 0
                """,
                (table, *uniq),
            )
        except Exception:
            continue
        for row in rows:
            cn = (row.get("contract_number") or "").strip()
            if cn:
                numbers_with_hits.add((table, cn))

    hit_ids: set[int] = set()
    for link in links:
        table = (link.get("tender_table") or "").strip()
        number = (link.get("tender_number") or "").strip()
        exp_id = link.get("expertise_id")
        if exp_id is not None and (table, number) in numbers_with_hits:
            hit_ids.add(int(exp_id))
    return hit_ids


def _forecast(row: dict) -> dict:
    exp_date = _to_date(row.get("expertise_date"))
    predicted = exp_date + timedelta(days=AVERAGE_DAYS_TO_TENDER) if exp_date else None
    days_left = (predicted - date.today()).days if predicted else None
    if days_left is None:
        phase = "no_date"
        priority = 20
    elif days_left < -30:
        phase = "overdue_check_tender"
        priority = 70
    elif days_left <= 30:
        phase = "hot_expected"
        priority = 95
    elif days_left <= 90:
        phase = "warm_expected"
        priority = 80
    elif days_left <= 180:
        phase = "nurture"
        priority = 55
    else:
        phase = "early_watch"
        priority = 35

    return {
        "predicted_tender_date": predicted.isoformat() if predicted else None,
        "days_to_predicted_tender": days_left,
        "radar_phase": phase,
        "radar_priority": priority,
        "source_type": "positive_expertise",
        "source_label": "Положительное заключение",
    }


def _guess_region(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    first_chunk = str(text).split(",", 1)[0].strip()
    if any(marker in first_chunk.lower() for marker in ("обл", "край", "респ", "г.", "город", "москва", "санкт")):
        return first_chunk
    return None


def _to_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def build_radar_ai_payload(row: dict) -> dict:
    """Payload that can be fed into local AI / CRM advisor."""
    return {
        "source": row.get("source_label"),
        "expertise_number": row.get("expertise_number"),
        "expertise_date": str(row.get("expertise_date") or ""),
        "predicted_tender_date": row.get("predicted_tender_date"),
        "days_to_predicted_tender": row.get("days_to_predicted_tender"),
        "object_name": row.get("object_name"),
        "region": row.get("region_name"),
        "developer": row.get("developer_organization_info"),
        "technical_customer": row.get("technical_customer_organization_info"),
        "planner": row.get("planner_organization_info"),
        "expertise_organization": row.get("expertise_organization_info"),
        "work_type": row.get("work_type"),
        "segment": row.get("segment"),
        "segment_keywords": row.get("segment_keywords"),
        "tender_match_count": row.get("tender_match_count"),
        "radar_phase": row.get("radar_phase"),
        "radar_priority": row.get("radar_priority"),
        "product_interest": row.get("product_interest_labels") or [],
        "crm_goal": (
            "Создать раннюю карточку объекта до выхода закупки или до разбора документов: "
            "найти цепочку участников, поставить объект на наблюдение, подготовить контакт "
            "с заказчиком, балансодержателем или проектировщиком. Не утверждать материалы "
            "без совпадений в документации."
        ),
    }


def rss_placeholder_rows() -> list[dict]:
    """Static placeholder until RSS ingestion is connected."""
    return [
        {
            "source_type": "rss_news",
            "source_label": "RSS / новости",
            "object_name": "Будущий новостной сигнал: чиновник сообщил о строительстве или ремонте",
            "region_name": "будет извлечено из новости",
            "radar_phase": "planned",
            "radar_priority": 0,
            "predicted_tender_date": None,
            "days_to_predicted_tender": None,
            "product_interest_labels": [],
            "note": "Следующий этап: RSS-лента → извлечение региона/объекта → первичная CRM-карточка.",
        }
    ]


def product_filter_options() -> list[tuple[str, str]]:
    return [("all", "Все направления")] + list(PRODUCT_GROUP_OPTIONS)
