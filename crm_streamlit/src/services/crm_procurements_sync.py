"""Синхронизация закупок из tender_monitor → crm_procurements.

Архитектура:
  1. match_cache_refresh() — читает crm_search_rules из crm DB, матчит по auction_name
     в tender_monitor (READ ONLY) и записывает результат в crm_tender_match_cache (crm DB).
  2. sync_torgi()   — читает cache из crm_db, source rows из tender_db → crm_procurements.
  3. sync_awarded() — проверяет awarded-таблицы для записей в стадии ожидания.
  4. sync_all_processed() — (CRM-SYNC-1) синхронизирует ВСЕ объекты, обработанные
     daemon'ом (с docs/matches/evidence), не ограничиваясь keyword-матчем.

SYNC_SOURCE_ROLE=SOURCE_DB (tender_monitor READ ONLY)
SYNC_TARGET_ROLE=CRM_DB
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import psycopg2.extras

from src.services.source_db_readonly import ensure_match_cache_table

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

# CRM-SYNC-1: все источники, включая awarded и commission
SOURCE_CONFIGS = [
    # (src_table,                              cust_col,   crm_stage,    lifecycle_type)
    ("reestr_contract_44_fz",                  "customer", "torgi",      "OPEN"),
    ("reestr_contract_223_fz",                 "placer",   "torgi",      "OPEN"),
    ("reestr_contract_44_fz_awarded",          "customer", "razygranye", "AWARDED"),
    ("reestr_contract_223_fz_awarded",         "placer",   "razygranye", "AWARDED"),
    ("reestr_contract_44_fz_commission_work",  "customer", "commission", "COMMISSION"),
    ("reestr_contract_223_fz_commission_work", "placer",   "commission", "COMMISSION"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tender_dict_query(tender_db, sql: str, params: dict | None = None) -> list[dict]:
    """Выполняет SELECT в tender_db и возвращает список dict (RealDictCursor)."""
    conn = tender_db.get_connection()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Существующие функции (match_cache_refresh, sync_torgi, sync_awarded)
# ---------------------------------------------------------------------------

def match_cache_refresh(tender_db, crm_db, since_days: int = 180) -> dict:
    """Refresh CRM-owned crm_tender_match_cache.

    READ: source procurement titles via tender_db (source_db).
    WRITE: crm_tender_match_cache via crm_db only.
    MATCH_CACHE_OWNER=CRM_DB
    """
    since = date.today() - timedelta(days=since_days)

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

    try:
        ensure_match_cache_table(crm_db)
    except Exception as exc:
        logger.error(f"match_cache table missing on crm_db (no auto-DDL): {exc}")
        return {"error": "SCHEMA_NOT_READY", "missing": "crm_tender_match_cache"}

    total = 0
    for src_table, cust_col, _label in _SOURCE_TABLES:
        try:
            rows = _tender_dict_query(
                tender_db,
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
                        crm_db.execute_update("""
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
                        logger.warning(f"match cache insert (crm_db): {exc}")

    return {"cached": total, "write_role": "crm_db"}


def _crm_dict_query(crm_db, sql: str, params: dict | None = None) -> list[dict]:
    rows = crm_db.execute_query(sql, params) or []
    if not rows:
        return []
    if isinstance(rows[0], dict):
        return list(rows)
    # tuple rows without column names — unsupported for this helper
    return [dict(r) if hasattr(r, "keys") else r for r in rows]


def sync_torgi(tender_db, crm_db, since_days: int = 180) -> dict:
    """Переносит записи из CRM crm_tender_match_cache → crm_procurements.

    Cache READ: crm_db. Source procurement READ: tender_db. WRITE: crm_db.
    """
    from src.services.crm_procurements_schema import ensure_schema
    if not ensure_schema(crm_db):
        return {"error": "SCHEMA_NOT_READY", "missing": "crm_procurements"}

    total = 0
    for src_table, cust_col, _label in _SOURCE_TABLES:
        try:
            cache_rows = crm_db.execute_query(
                """
                SELECT source_id, crm_profile_id, match_score, matched_keywords
                FROM crm_tender_match_cache
                WHERE source_table = %(st)s
                """,
                {"st": src_table},
            ) or []
        except Exception as exc:
            logger.error(f"sync_torgi cache pull {src_table}: {exc}")
            continue

        if not cache_rows:
            continue

        # Normalize cache rows to dicts
        normalized = []
        for r in cache_rows:
            if isinstance(r, dict):
                normalized.append(r)
            else:
                normalized.append(
                    {
                        "source_id": r[0],
                        "crm_profile_id": r[1],
                        "match_score": r[2],
                        "matched_keywords": r[3],
                    }
                )

        source_ids = sorted({int(r["source_id"]) for r in normalized})
        cache_by_sid: dict[int, list] = defaultdict(list)
        for r in normalized:
            cache_by_sid[int(r["source_id"])].append(r)

        try:
            rows = _tender_dict_query(
                tender_db,
                f"""
                SELECT c.id AS source_id,
                    c.contract_number, c.auction_name, c.initial_price, c.final_price,
                    c.{cust_col} AS customer, c.delivery_region, c.region_id,
                    o.main_code AS okpd_code, o.name AS okpd_name,
                    ct.short_name AS contractor_name, ct.inn AS contractor_inn,
                    c.start_date, c.end_date, c.delivery_start_date, c.delivery_end_date,
                    c.tender_link, c.updated_at AS source_updated_at
                FROM {src_table} c
                LEFT JOIN collection_codes_okpd o ON o.id = c.okpd_id
                LEFT JOIN contractor ct ON ct.id = c.contractor_id
                WHERE c.id = ANY(%(ids)s::int[])
                """,
                {"ids": source_ids},
            )
        except Exception as exc:
            logger.error(f"sync_torgi source pull {src_table}: {exc}")
            continue

        for row in rows:
            sid = int(row["source_id"])
            for m in cache_by_sid.get(sid, []):
                end_date = row.get("end_date")
                today = date.today()
                if end_date is None or today <= end_date:
                    award_status = "submission_open"
                else:
                    award_status = "submission_closed_waiting_award"

                profile_id = m.get("crm_profile_id")
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
                        "source_id": sid,
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
                        "profile_id": profile_id,
                        "category": _PROFILE_NAMES.get(profile_id, ""),
                        "score": m.get("match_score", 0),
                        "keywords": list(m.get("matched_keywords") or []),
                    })
                    total += 1
                except Exception as exc:
                    logger.warning(f"sync_torgi upsert {src_table}/{sid}: {exc}")

    return {"synced": total, "read_cache_role": "crm_db"}


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
            awarded_rows = _tender_dict_query(tender_db, f"""
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


# ---------------------------------------------------------------------------
# CRM-SYNC-1: sync_all_processed
# ---------------------------------------------------------------------------

def _acquire_sync_lock(crm_db) -> int | None:
    """Создаёт job-запись со status='running'. Возвращает job.id или None если уже запущен."""
    running = crm_db.execute_query(
        "SELECT id FROM crm_sync_jobs WHERE status = 'running' LIMIT 1"
    )
    if running:
        logger.warning(f"sync_all_processed: already running (job {running[0]['id']}), skip")
        return None

    crm_db.execute_update("""
        INSERT INTO crm_sync_jobs
            (job_type, trigger_type, requested_by, status, started_at, created_at)
        VALUES ('sync_all_processed', 'scheduled', 'runner', 'running', now(), now())
    """)
    # Fetch the id we just inserted (last row by id)
    job = crm_db.execute_query(
        "SELECT id FROM crm_sync_jobs ORDER BY id DESC LIMIT 1"
    )
    return job[0]["id"] if job else None


def _finish_sync_job(crm_db, job_id: int, counts: dict, error: str | None = None) -> None:
    status = "error" if error else "ok"
    crm_db.execute_update("""
        UPDATE crm_sync_jobs SET
            status          = %(status)s,
            finished_at     = now(),
            processed_count = %(processed)s,
            updated_count   = %(updated)s,
            awarded_count   = %(awarded)s,
            not_found_count = %(not_found)s,
            error_count     = %(errors)s,
            error_message   = %(error_msg)s
        WHERE id = %(job_id)s
    """, {
        "status":    status,
        "processed": counts.get("inserted", 0),
        "updated":   counts.get("updated", 0),
        "awarded":   counts.get("awarded", 0),
        "not_found": counts.get("not_found", 0),
        "errors":    counts.get("errors", 0),
        "error_msg": error,
        "job_id":    job_id,
    })


def sync_all_processed(
    tender_db,
    crm_db,
    watermark: Optional[datetime] = None,
) -> dict:
    """Синхронизирует ВСЕ объекты, обработанные daemon'ом, в crm_procurements.

    Критерий попадания: хотя бы одна запись в tender_document_matches
    или processed_documents с данным tender_id.

    Идемпотентна: повторный запуск обновляет агрегаты, не создаёт дублей.
    UPSERT по (source_table, source_id).
    qualification_state и crm_stage не перезаписываются если уже изменены вручную.

    Args:
        tender_db:  DB wrapper tender_monitor
        crm_db:     DB wrapper crm
        watermark:  если задан — берём только объекты, обновлённые после этой метки

    Returns:
        dict: inserted, updated, awarded, not_found, errors, skipped_lock
    """
    counts: dict[str, int] = {
        "inserted": 0, "updated": 0, "awarded": 0,
        "not_found": 0, "errors": 0, "skipped_lock": 0,
    }

    job_id = _acquire_sync_lock(crm_db)
    if job_id is None:
        counts["skipped_lock"] = 1
        return counts

    try:
        _sync_body(tender_db, crm_db, watermark, counts)
    except Exception as exc:
        logger.error(f"sync_all_processed fatal: {exc}")
        _finish_sync_job(crm_db, job_id, counts, error=str(exc))
        raise

    _finish_sync_job(crm_db, job_id, counts)
    # Optional: integrate commercial opportunity lifecycle sync (S7 authority → S13 consumer).
    # Kept feature-flagged and default dry-run to avoid production writes in current WIP.
    if os.getenv("COMMERCIAL_ROUTING_V3_LIFECYCLE_SYNC_ENABLED", "0") == "1":
        try:
            from src.services.commercial_routing_v3.opportunity_lifecycle_sync import (
                sync_opportunities_lifecycle,
            )

            dry_run = os.getenv("COMMERCIAL_ROUTING_V3_LIFECYCLE_SYNC_DRY_RUN", "1") == "1"
            lifecycle_res = sync_opportunities_lifecycle(
                crm_db,
                dry_run=dry_run,
            )
            counts["lifecycle_sync_updated"] = int(lifecycle_res.get("transitions") or 0)
            counts["lifecycle_sync_skipped"] = int(lifecycle_res.get("skipped") or 0)
        except Exception as exc:
            logger.warning("commercial lifecycle sync failed: %s", exc)

    logger.info(f"sync_all_processed done: {counts}")
    return counts


def _sync_body(tender_db, crm_db, watermark, counts: dict) -> None:
    # 1. Все processed tender_id из tender_monitor (один запрос — UNION обоих источников)
    wm_clause_m = " WHERE updated_at >= %(wm)s" if watermark else ""
    wm_clause_p = " WHERE updated_at >= %(wm)s" if watermark else ""
    wm_params = {"wm": watermark} if watermark else None

    raw = tender_db.execute_query(
        f"SELECT DISTINCT tender_id FROM tender_document_matches{wm_clause_m}"
        f" UNION SELECT DISTINCT tender_id FROM processed_documents{wm_clause_p}",
        wm_params,
    )
    # tender_db возвращает tuples → r[0]
    all_ids = list({r[0] for r in raw} if raw else set())

    if not all_ids:
        logger.info("sync_all_processed: no processed tender_ids found")
        return

    logger.info(f"sync_all_processed: {len(all_ids)} processed tender_ids")

    # 2. UPSERT по каждому источнику
    for src_table, cust_col, crm_stage, lifecycle in SOURCE_CONFIGS:
        _sync_source(tender_db, crm_db, src_table, cust_col, crm_stage, all_ids, counts)

    # 3. Batch-обновление агрегатов
    _update_aggregates(tender_db, crm_db)

    # 4. Повысить qualification_state: unassessed → candidate если match_count > 0
    try:
        crm_db.execute_update("""
            UPDATE crm_procurements
            SET qualification_state = 'candidate',
                crm_updated_at = now()
            WHERE qualification_state = 'unassessed'
              AND match_count > 0
        """)
    except Exception as exc:
        logger.warning(f"qualification_state upgrade: {exc}")


def _sync_source(
    tender_db,
    crm_db,
    src_table: str,
    cust_col: str,
    crm_stage: str,
    all_ids: list[int],
    counts: dict,
) -> None:
    """UPSERT одного источника в crm_procurements."""
    try:
        rows = _tender_dict_query(
            tender_db,
            f"""
            SELECT
                c.id                   AS source_id,
                c.contract_number,
                c.auction_name,
                c.initial_price,
                c.final_price,
                c.{cust_col}           AS customer,
                c.delivery_region,
                c.region_id,
                c.start_date,
                c.end_date,
                c.delivery_start_date,
                c.delivery_end_date,
                c.tender_link,
                c.updated_at           AS source_updated_at
            FROM {src_table} c
            WHERE c.id = ANY(%(ids)s)
            """,
            {"ids": all_ids},
        )
    except Exception as exc:
        logger.error(f"_sync_source pull {src_table}: {exc}")
        counts["errors"] += 1
        return

    logger.info(f"_sync_source {src_table}: {len(rows)} rows")

    for row in rows:
        try:
            end_date = row.get("end_date")
            today = date.today()
            if crm_stage == "torgi":
                award_status = (
                    "submission_open"
                    if end_date is None or today <= end_date
                    else "submission_closed_waiting_award"
                )
            elif crm_stage == "razygranye":
                award_status = "awarded"
            else:
                award_status = "commission"

            crm_db.execute_update("""
                INSERT INTO crm_procurements (
                    source_table, source_id, contract_number, auction_name,
                    initial_price, final_price, customer, delivery_region, region_id,
                    start_date, end_date, delivery_start_date, delivery_end_date,
                    tender_link, source_updated_at,
                    crm_stage, award_status,
                    qualification_state
                ) VALUES (
                    %(source_table)s, %(source_id)s, %(contract_number)s, %(auction_name)s,
                    %(initial_price)s, %(final_price)s, %(customer)s, %(delivery_region)s, %(region_id)s,
                    %(start_date)s, %(end_date)s, %(delivery_start_date)s, %(delivery_end_date)s,
                    %(tender_link)s, %(source_updated_at)s,
                    %(crm_stage)s, %(award_status)s,
                    'unassessed'
                )
                ON CONFLICT (source_table, source_id) DO UPDATE SET
                    auction_name      = EXCLUDED.auction_name,
                    initial_price     = EXCLUDED.initial_price,
                    end_date          = EXCLUDED.end_date,
                    source_updated_at = EXCLUDED.source_updated_at,
                    crm_updated_at    = now()
                WHERE crm_procurements.crm_stage NOT IN ('manual_hold')
            """, {
                "source_table":      src_table,
                "source_id":         row["source_id"],
                "contract_number":   row.get("contract_number"),
                "auction_name":      row.get("auction_name"),
                "initial_price":     row.get("initial_price"),
                "final_price":       row.get("final_price"),
                "customer":          row.get("customer"),
                "delivery_region":   row.get("delivery_region"),
                "region_id":         row.get("region_id"),
                "start_date":        row.get("start_date"),
                "end_date":          end_date,
                "delivery_start_date": row.get("delivery_start_date"),
                "delivery_end_date": row.get("delivery_end_date"),
                "tender_link":       row.get("tender_link"),
                "source_updated_at": row.get("source_updated_at"),
                "crm_stage":         crm_stage,
                "award_status":      award_status,
            })

            counts["inserted"] += 1
            if crm_stage == "razygranye":
                counts["awarded"] += 1

        except Exception as exc:
            logger.warning(f"upsert {src_table}/{row.get('source_id')}: {exc}")
            counts["errors"] += 1


def _update_aggregates(tender_db, crm_db) -> None:
    """Обновляет match_count, evidence_count, interesting_count, last_daemon_at.

    Двухшаговый подход (два DB, cross-DB JOIN невозможен):
      1. Читаем агрегаты из tender_db → Python list
      2. Batch UPDATE crm_db через execute_many (один commit, без N+1)
    """
    # --- матчи / evidence ---
    try:
        agg_rows = _tender_dict_query(tender_db, """
            SELECT
                m.tender_id,
                COUNT(DISTINCT m.id)                                       AS match_count,
                COUNT(DISTINCT CASE WHEN m.is_interesting THEN m.id END)   AS interesting_count,
                COUNT(d.id)                                                AS evidence_count,
                MAX(m.processed_at)                                        AS last_processed_at
            FROM tender_document_matches m
            LEFT JOIN tender_document_match_details d ON d.match_id = m.id
            GROUP BY m.tender_id
        """)
    except Exception as exc:
        logger.warning(f"_update_aggregates fetch matches: {exc}")
        agg_rows = []

    if agg_rows:
        try:
            params_list = [
                {
                    "match_count":       r["match_count"],
                    "interesting_count": r["interesting_count"],
                    "evidence_count":    r["evidence_count"],
                    "last_processed_at": r.get("last_processed_at"),
                    "tender_id":         r["tender_id"],
                }
                for r in agg_rows
            ]
            crm_db.execute_many("""
                UPDATE crm_procurements SET
                    match_count       = %(match_count)s,
                    interesting_count = %(interesting_count)s,
                    evidence_count    = %(evidence_count)s,
                    last_daemon_at    = %(last_processed_at)s,
                    crm_updated_at    = now()
                WHERE source_id = %(tender_id)s
            """, params_list)
            logger.info(f"_update_aggregates: batch-updated {len(agg_rows)} match/evidence rows")
        except Exception as exc:
            logger.warning(f"_update_aggregates batch match: {exc}")

    # --- file_count из processed_documents ---
    try:
        file_rows = _tender_dict_query(tender_db, """
            SELECT tender_id, COUNT(*) AS file_count
            FROM processed_documents
            GROUP BY tender_id
        """)
    except Exception as exc:
        logger.warning(f"_update_aggregates fetch files: {exc}")
        file_rows = []

    if file_rows:
        try:
            crm_db.execute_many("""
                UPDATE crm_procurements SET file_count = %(file_count)s
                WHERE source_id = %(tender_id)s
            """, [{"file_count": r["file_count"], "tender_id": r["tender_id"]} for r in file_rows])
            logger.info(f"_update_aggregates: batch-updated {len(file_rows)} file_count rows")
        except Exception as exc:
            logger.warning(f"_update_aggregates batch file_count: {exc}")
