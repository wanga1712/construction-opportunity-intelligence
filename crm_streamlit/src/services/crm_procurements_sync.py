"""Синхронизация закупок из tender_monitor → crm_procurements.

Архитектура:
  1. match_cache_refresh() — читает crm_search_rules из crm DB, матчит по auction_name
     в tender_monitor и записывает результат в crm_tender_match_cache (tender_monitor).
  2. sync_torgi()   — переносит записи из match_cache в crm_procurements (crm DB).
  3. sync_awarded() — проверяет awarded-таблицы для записей в стадии ожидания.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_PROFILE_NAMES = {
    1: "Напольные покрытия",
    2: "Стандартпарк / Гидроизоляция",
    3: "Компьютеры / ИТ",
    8: "Светотехника",
    9: "Композиты",
}

_SOURCE_TABLES = [
    ("reestr_contract_44_fz",  "customer",  "44-ФЗ"),
    ("reestr_contract_223_fz", "placer",    "223-ФЗ"),
]

_AWARDED_TABLES = {
    "reestr_contract_44_fz":  "reestr_contract_44_fz_awarded",
    "reestr_contract_223_fz": "reestr_contract_223_fz_awarded",
}


def match_cache_refresh(tender_db, crm_db, since_days: int = 180) -> dict:
    """Обновляет crm_tender_match_cache на основе ключевых слов из crm_search_rules."""
    import psycopg2
    import psycopg2.extras

    since = date.today() - timedelta(days=since_days)

    # 1. Читаем правила
    try:
        rules = crm_db.execute_query("""
            SELECT search_profile_id, value, weight
            FROM crm_search_rules
            WHERE is_active = true AND rule_type = 'include_keyword'
        """)
    except Exception as exc:
        logger.error(f"match_cache_refresh read rules: {exc}")
        return {"error": str(exc)}

    profile_kws: dict[int, list] = defaultdict(list)
    for r in rules:
        profile_kws[r["search_profile_id"]].append((r["value"], r["weight"]))

    if not profile_kws:
        return {"error": "no keywords in crm_search_rules"}

    # 2. Создаём таблицу если нет
    try:
        tender_db.execute_update("""
            CREATE TABLE IF NOT EXISTS crm_tender_match_cache (
                id               SERIAL PRIMARY KEY,
                source_table     TEXT NOT NULL,
                source_id        INTEGER NOT NULL,
                crm_profile_id   INTEGER NOT NULL,
                match_score      INTEGER NOT NULL DEFAULT 0,
                matched_keywords TEXT[],
                matched_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (source_table, source_id, crm_profile_id)
            )
        """)
    except Exception as exc:
        logger.warning(f"match_cache table: {exc}")

    total = 0
    for src_table, cust_col, _label in _SOURCE_TABLES:
        try:
            rows = tender_db.execute_query(
                f"SELECT id, auction_name FROM {src_table} WHERE end_date >= %(since)s",
                {"since": since},
            )
        except Exception as exc:
            logger.error(f"match_cache pull {src_table}: {exc}")
            continue

        for row in rows:
            name_lower = (row.get("auction_name") or "").lower()
            for profile_id, kws in profile_kws.items():
                score = 0
                matched = []
                for kw, weight in kws:
                    if kw.lower() in name_lower:
                        score += weight
                        matched.append(kw)
                if score > 0:
                    try:
                        tender_db.execute_update("""
                            INSERT INTO crm_tender_match_cache
                                (source_table, source_id, crm_profile_id, match_score, matched_keywords)
                            VALUES (%(st)s, %(sid)s, %(pid)s, %(sc)s, %(kw)s)
                            ON CONFLICT (source_table, source_id, crm_profile_id) DO UPDATE SET
                                match_score = EXCLUDED.match_score,
                                matched_keywords = EXCLUDED.matched_keywords,
                                matched_at = now()
                        """, {"st": src_table, "sid": row["id"], "pid": profile_id,
                              "sc": score, "kw": matched})
                        total += 1
                    except Exception as exc:
                        logger.warning(f"match cache insert: {exc}")

    return {"cached": total}


def sync_torgi(tender_db, crm_db, since_days: int = 180) -> dict:
    """Переносит записи из crm_tender_match_cache → crm_procurements."""
    from src.services.crm_procurements_schema import ensure_schema
    if not ensure_schema(crm_db):
        return {"error": "schema init failed"}

    total = 0
    for src_table, cust_col, _label in _SOURCE_TABLES:
        try:
            rows = tender_db.execute_query(f"""
                SELECT m.source_id, m.crm_profile_id, m.match_score, m.matched_keywords,
                    c.contract_number, c.auction_name, c.initial_price, c.final_price,
                    c.{cust_col} AS customer, c.delivery_region, c.region_id,
                    o.main_code AS okpd_code, o.name AS okpd_name,
                    ct.short_name AS contractor_name, ct.inn AS contractor_inn,
                    c.start_date, c.end_date, c.delivery_start_date, c.delivery_end_date,
                    c.tender_link, c.updated_at AS source_updated_at
                FROM crm_tender_match_cache m
                JOIN {src_table} c ON c.id = m.source_id
                LEFT JOIN collection_codes_okpd o ON o.id = c.okpd_id
                LEFT JOIN contractor ct ON ct.id = c.contractor_id
                WHERE m.source_table = %(st)s
            """, {"st": src_table})
        except Exception as exc:
            logger.error(f"sync_torgi pull {src_table}: {exc}")
            continue

        for row in rows:
            end_date = row.get("end_date")
            today = date.today()
            if end_date is None or today <= end_date:
                award_status = "submission_open"
            else:
                award_status = "submission_closed_waiting_award"

            try:
                crm_db.execute_update("""
                    INSERT INTO crm_procurements (
                        source_table, source_id, contract_number, auction_name,
                        initial_price, final_price, customer, delivery_region, region_id,
                        okpd_code, okpd_name, contractor_name, contractor_inn,
                        start_date, end_date, delivery_start_date, delivery_end_date,
                        tender_link, source_updated_at, crm_stage, award_status,
                        crm_profile_id, crm_category, match_score, matched_keywords
                    ) VALUES (
                        %(source_table)s, %(source_id)s, %(contract_number)s, %(auction_name)s,
                        %(initial_price)s, %(final_price)s, %(customer)s, %(delivery_region)s, %(region_id)s,
                        %(okpd_code)s, %(okpd_name)s, %(contractor_name)s, %(contractor_inn)s,
                        %(start_date)s, %(end_date)s, %(delivery_start_date)s, %(delivery_end_date)s,
                        %(tender_link)s, %(source_updated_at)s, 'torgi', %(award_status)s,
                        %(profile_id)s, %(category)s, %(score)s, %(keywords)s
                    )
                    ON CONFLICT (source_table, source_id) DO UPDATE SET
                        auction_name = EXCLUDED.auction_name,
                        initial_price = EXCLUDED.initial_price,
                        end_date = EXCLUDED.end_date,
                        award_status = EXCLUDED.award_status,
                        crm_profile_id = EXCLUDED.crm_profile_id,
                        crm_category = EXCLUDED.crm_category,
                        match_score = EXCLUDED.match_score,
                        matched_keywords = EXCLUDED.matched_keywords,
                        crm_updated_at = now()
                    WHERE crm_procurements.crm_stage = 'torgi'
                """, {
                    "source_table": src_table,
                    "source_id": row["source_id"],
                    "contract_number": row.get("contract_number"),
                    "auction_name": row.get("auction_name"),
                    "initial_price": row.get("initial_price"),
                    "final_price": row.get("final_price"),
                    "customer": row.get("customer"),
                    "delivery_region": row.get("delivery_region"),
                    "region_id": row.get("region_id"),
                    "okpd_code": row.get("okpd_code"),
                    "okpd_name": row.get("okpd_name"),
                    "contractor_name": row.get("contractor_name"),
                    "contractor_inn": row.get("contractor_inn"),
                    "start_date": row.get("start_date"),
                    "end_date": end_date,
                    "delivery_start_date": row.get("delivery_start_date"),
                    "delivery_end_date": row.get("delivery_end_date"),
                    "tender_link": row.get("tender_link"),
                    "source_updated_at": row.get("source_updated_at"),
                    "award_status": award_status,
                    "profile_id": row.get("crm_profile_id"),
                    "category": _PROFILE_NAMES.get(row.get("crm_profile_id"), ""),
                    "score": row.get("match_score", 0),
                    "keywords": list(row.get("matched_keywords") or []),
                })
                total += 1
            except Exception as exc:
                logger.warning(f"upsert {src_table}/{row.get('source_id')}: {exc}")

    return {"upserted": total}


def sync_awarded(tender_db, crm_db) -> dict:
    """Проверяет awarded-реестры для закупок в периоде ожидания."""
    try:
        pending = crm_db.execute_query("""
            SELECT id, source_table, contract_number, end_date, post_submission_grace_days
            FROM crm_procurements
            WHERE crm_stage = 'torgi'
              AND award_status != 'awarded'
              AND end_date < current_date
        """)
    except Exception as exc:
        logger.error(f"sync_awarded fetch pending: {exc}")
        return {"error": str(exc)}

    awarded_count = not_found_count = 0
    by_source: dict[str, list] = defaultdict(list)
    for row in pending:
        by_source[row["source_table"]].append(row)

    for source_table, rows in by_source.items():
        awarded_table = _AWARDED_TABLES.get(source_table)
        if not awarded_table:
            continue

        numbers = [r["contract_number"] for r in rows]
        try:
            awarded_rows = tender_db.execute_query(f"""
                SELECT a.id, a.contract_number, a.final_price,
                    a.start_date AS contract_signed_at,
                    a.delivery_start_date AS execution_start_at,
                    a.delivery_end_date AS execution_end_at,
                    ct.short_name AS winner_name, ct.inn AS winner_inn
                FROM {awarded_table} a
                LEFT JOIN contractor ct ON ct.id = a.contractor_id
                WHERE a.contract_number = ANY(%(numbers)s)
            """, {"numbers": numbers})
        except Exception as exc:
            logger.error(f"sync_awarded query {awarded_table}: {exc}")
            continue

        awarded_by_num = {r["contract_number"]: r for r in awarded_rows}

        for proc in rows:
            num = proc["contract_number"]
            grace = proc["post_submission_grace_days"]
            end_date = proc["end_date"]

            if num in awarded_by_num:
                aw = awarded_by_num[num]
                try:
                    crm_db.execute_update("""
                        UPDATE crm_procurements SET
                            crm_stage            = 'razygranye',
                            award_status         = 'awarded',
                            winner_name          = %(winner_name)s,
                            winner_inn           = %(winner_inn)s,
                            final_contract_price = %(final_price)s,
                            contract_signed_at   = %(contract_signed_at)s,
                            execution_start_at   = %(execution_start_at)s,
                            execution_end_at     = %(execution_end_at)s,
                            source_awarded_table = %(awarded_table)s,
                            source_awarded_id    = %(awarded_id)s,
                            awarded_match_type   = 'exact_contract_number',
                            awarded_match_confidence = 1.0,
                            commercial_window_state = 'contractor_selected_supply_open',
                            crm_updated_at       = now()
                        WHERE id = %(id)s
                    """, {
                        "winner_name": aw.get("winner_name"),
                        "winner_inn": aw.get("winner_inn"),
                        "final_price": aw.get("final_price"),
                        "contract_signed_at": aw.get("contract_signed_at"),
                        "execution_start_at": aw.get("execution_start_at"),
                        "execution_end_at": aw.get("execution_end_at"),
                        "awarded_table": awarded_table,
                        "awarded_id": aw.get("id"),
                        "id": proc["id"],
                    })
                    awarded_count += 1
                except Exception as exc:
                    logger.warning(f"update awarded {proc['id']}: {exc}")
            else:
                today = date.today()
                new_status = (
                    "award_not_found"
                    if end_date and today > end_date + timedelta(days=grace)
                    else "submission_closed_waiting_award"
                )
                try:
                    crm_db.execute_update("""
                        UPDATE crm_procurements SET
                            award_status = %(status)s,
                            last_award_check_at = now(),
                            crm_updated_at = now()
                        WHERE id = %(id)s
                    """, {"status": new_status, "id": proc["id"]})
                    not_found_count += 1
                except Exception as exc:
                    logger.warning(f"update not_found {proc['id']}: {exc}")

    return {"awarded": awarded_count, "not_found": not_found_count}
