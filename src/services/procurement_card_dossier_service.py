"""Read-only «досье закупки» для UI-карточки (гибрид 1С/Битрикс).

Собирает максимум доступной информации по одной закупке из существующих
источников, ничего не считая и не записывая:

* CRM ``crm_procurements``     — стороны, ссылка, деньги, даты, стадия;
* CRM ``crm_objects_index``    — балансодержатель (если объект привязан);
* CRM ``crm_procurement_category_opportunities`` — категории/медаль/трек;
* DI  ``document_files``       — что скачано / можно ли скачать;
* DI  ``document_match_details`` (+ matches/files) — что найдено в документах,
  включая retrieval-provenance (VERIFIED/INVALID/LEGACY_UNVERIFIED).

Все секции fail-soft: недоступная таблица → пустая секция + ``errors``, страница
не падает. Никаких записей в БД.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger("crm.procurement_card_dossier")

DI = "document_intelligence"

_DI_CONN: Any = None


def _di_conn() -> Any:
    """Read-only подключение к document_intelligence.

    Использует принятый в этом приложении паттерн (см.
    ``analytics_table_workspace_service._attach_queue_status``): CRM-креды с
    подменой ``dbname`` на document_intelligence.
    """
    global _DI_CONN
    if _DI_CONN is not None and getattr(_DI_CONN, "closed", 1) == 0:
        return _DI_CONN
    from src.services.crm_db_runtime import require_crm_db_connect_kwargs

    kwargs = dict(require_crm_db_connect_kwargs())
    kwargs["dbname"] = os.getenv("S13_DOCUMENT_DB_NAME", DI)
    kwargs.setdefault("connect_timeout", 8)
    _DI_CONN = psycopg2.connect(**kwargs)
    return _DI_CONN


def _safe_di(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    try:
        conn = _di_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in (cur.fetchall() or [])]
    except Exception as exc:  # noqa: BLE001
        logger.warning("dossier DI query failed: %s", exc)
        return []


def _di_write_conn() -> Any:
    """Отдельное autocommit-подключение для управляемой постановки в очередь."""
    from src.services.crm_db_runtime import require_crm_db_connect_kwargs

    kwargs = dict(require_crm_db_connect_kwargs())
    kwargs["dbname"] = os.getenv("S13_DOCUMENT_DB_NAME", DI)
    kwargs.setdefault("connect_timeout", 8)
    conn = psycopg2.connect(**kwargs)
    conn.autocommit = True
    return conn


def _safe(db: Any, alias: Optional[str], sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    if db is None:
        return []
    try:
        if alias:
            try:
                rows = db.execute_query(alias, sql, params, fetch=True)
            except TypeError:
                rows = db.execute_query(sql, params)
        else:
            try:
                rows = db.execute_query(sql, params)
            except TypeError:
                rows = db.execute_query(sql, params, fetch=True)
        return [dict(r) if not isinstance(r, dict) else r for r in (rows or [])]
    except Exception as exc:  # noqa: BLE001 - карточка не должна падать
        logger.warning("dossier query failed (%s): %s", alias or "crm", exc)
        return []


def list_procurements_for_card(
    db: Any, *, search_text: Optional[str] = None, limit: int = 200
) -> List[Dict[str, Any]]:
    """Компактный список закупок для левой колонки карточки.

    Порядок (как просил заказчик): сначала те, по которым уже есть данные
    (что-то распарсили), затем те, что стоят в очереди, затем остальные;
    внутри группы — по медали GOLD → SILVER → BRONZE → WOOD.
    """
    sql = """
        SELECT id, contract_number, auction_name, customer, initial_price,
               okpd_code, crm_stage, award_status, end_date, tender_link
        FROM crm_procurements
        WHERE (%s IS NULL OR auction_name ILIKE %s OR contract_number ILIKE %s OR customer ILIKE %s)
        ORDER BY COALESCE(end_date, DATE '1900-01-01') DESC, id DESC
        LIMIT %s
    """
    token = f"%{search_text.strip()}%" if search_text and search_text.strip() else None
    # Rank globally enough rows BEFORE truncating, so parsed/queued procurements
    # reach the top instead of being cut off by the date window.
    fetch_n = min(800, max(int(limit) * 4, 200))
    rows = _safe(db, None, sql, (token, token, token, token, fetch_n))
    if not rows:
        return []
    ids = [int(r["id"]) for r in rows if r.get("id") is not None]

    medal_rank = {
        int(r["procurement_id"]): int(r.get("medal_rank") or 0)
        for r in _safe(
            db, None,
            """
            SELECT procurement_id,
                   MAX(CASE current_effective_medal
                         WHEN 'GOLD' THEN 4 WHEN 'SILVER' THEN 3
                         WHEN 'BRONZE' THEN 2 WHEN 'WOOD' THEN 1 ELSE 0 END) AS medal_rank
            FROM crm_procurement_category_opportunities
            WHERE status = 'CURRENT' AND procurement_id = ANY(%s)
            GROUP BY procurement_id
            """,
            (ids,),
        )
    }
    docs_done = {
        int(r["procurement_id"]): int(r.get("n") or 0)
        for r in _safe_di(
            """SELECT procurement_id, COUNT(*) AS n FROM document_files
               WHERE procurement_id = ANY(%s) AND download_status = 'COMPLETED'
               GROUP BY procurement_id""",
            (ids,),
        )
    }
    findings_n = {
        int(r["procurement_id"]): int(r.get("n") or 0)
        for r in _safe_di(
            """SELECT m.procurement_id, COUNT(*) AS n
               FROM document_match_details d JOIN document_matches m ON m.id = d.match_id
               WHERE m.procurement_id = ANY(%s) GROUP BY m.procurement_id""",
            (ids,),
        )
    }
    queue_state = {
        int(r["procurement_id"]): str(r.get("status") or "")
        for r in _safe_di(
            """SELECT DISTINCT ON (procurement_id) procurement_id, status
               FROM document_processing_queue WHERE procurement_id = ANY(%s)
               ORDER BY procurement_id, id DESC""",
            (ids,),
        )
    }
    for r in rows:
        pid = int(r["id"])
        parsed = docs_done.get(pid, 0) > 0 or findings_n.get(pid, 0) > 0
        qs = queue_state.get(pid, "").upper()
        in_queue = qs in ("PENDING", "PROCESSING", "PRE_RESEARCH_WAITING")
        r["medal_rank"] = medal_rank.get(pid, 0)
        r["documents_done"] = docs_done.get(pid, 0)
        r["findings"] = findings_n.get(pid, 0)
        r["queue_status"] = qs or None
        r["data_state"] = "PARSED" if parsed else ("QUEUED" if in_queue else "NONE")
        r["_group"] = 0 if parsed else (1 if in_queue else 2)
    rows.sort(key=lambda r: (r["_group"], -int(r.get("medal_rank") or 0), -(r.get("id") or 0)))
    return rows[: int(limit)]


def load_procurement_dossier(db: Any, procurement_id: int) -> Dict[str, Any]:
    """Собрать полное досье одной закупки."""
    dossier: Dict[str, Any] = {
        "procurement_id": int(procurement_id),
        "identity": {},
        "money_and_dates": {},
        "parties": {},
        "opportunities": [],
        "documents": [],
        "findings": [],
        "counts": {},
        "errors": [],
    }

    proc_rows = _safe(
        db,
        None,
        """
        SELECT id, contract_number, auction_name, customer, customer_source,
               customer_confidence, contractor_name, contractor_inn, winner_name,
               winner_inn, tender_link, source_table, crm_stage, award_status,
               okpd_code, okpd_name, initial_price, start_date, end_date,
               delivery_start_date, delivery_end_date, execution_start_at,
               execution_end_at, delivery_region,
               trading_platform, source_status, delivery_address,
               guarantee_amount, warranty_size
        FROM crm_procurements WHERE id = %s
        """,
        (int(procurement_id),),
    )
    if not proc_rows:
        dossier["errors"].append("procurement_not_found")
        return dossier
    p = proc_rows[0]

    src = str(p.get("source_table") or "")
    dossier["identity"] = {
        "id": p.get("id"),
        "contract_number": p.get("contract_number"),
        "auction_name": p.get("auction_name"),
        "tender_link": p.get("tender_link"),
        "law": "223-ФЗ" if "223" in src else ("44-ФЗ" if "44" in src else src or "—"),
        "source_table": src,
        "crm_stage": p.get("crm_stage"),
        "award_status": p.get("award_status"),
        "region": p.get("delivery_region"),
        "okpd_code": p.get("okpd_code"),
        "okpd_name": p.get("okpd_name"),
        "trading_platform": p.get("trading_platform"),
        "source_status": p.get("source_status"),
    }
    dossier["money_and_dates"] = {
        "initial_price": p.get("initial_price"),
        "guarantee_amount": p.get("guarantee_amount"),
        "warranty_size": p.get("warranty_size"),
        "delivery_address": p.get("delivery_address"),
        "start_date": p.get("start_date"),
        "end_date": p.get("end_date"),
        "delivery_start_date": p.get("delivery_start_date"),
        "delivery_end_date": p.get("delivery_end_date"),
        "execution_start_at": p.get("execution_start_at"),
        "execution_end_at": p.get("execution_end_at"),
    }
    dossier["parties"] = {
        "customer": p.get("customer"),
        "customer_source": p.get("customer_source"),
        "customer_confidence": p.get("customer_confidence"),
        "contractor": p.get("contractor_name"),
        "contractor_inn": p.get("contractor_inn"),
        "winner": p.get("winner_name"),
        "winner_inn": p.get("winner_inn"),
    }

    balance = _safe(
        db, None,
        "SELECT balance_holder FROM crm_objects_index WHERE tender_id = %s LIMIT 1",
        (int(procurement_id),),
    )
    dossier["parties"]["balance_holder"] = (
        balance[0].get("balance_holder") if balance else None
    )

    dossier["opportunities"] = _safe(
        db,
        None,
        """
        SELECT commercial_category_code, commercial_subcategory_code, opportunity_track,
               status, category_confidence, candidate_medal, current_effective_medal,
               commercial_priority_score, research_action
        FROM crm_procurement_category_opportunities
        WHERE procurement_id = %s
        ORDER BY commercial_priority_score DESC NULLS LAST, commercial_category_code
        """,
        (int(procurement_id),),
    )
    # Коммерческий режим: подтверждённый источник — scope gate (см. §2 WIP по карточке).
    scope_rows = _safe(
        db,
        None,
        """
        SELECT procurement_scope_type, scope_confidence, scope_method, scope_version,
               admission_state, admission_reason, scope_evaluated_at
        FROM crm_procurement_scope_authority
        WHERE procurement_id = %s
        LIMIT 1
        """,
        (int(procurement_id),),
    )
    dossier["scope"] = scope_rows[0] if scope_rows else {}
    # Ручные категории (MANUAL) — тот же источник данных, что и в таблице.
    try:
        from src.services.manual_category_service import list_manual_categories
        for m in list_manual_categories(db, int(procurement_id)):
            dossier["opportunities"].append({
                "commercial_category_code": m.get("category_code"),
                "commercial_subcategory_code": m.get("subcategory_code"),
                "opportunity_track": m.get("commercial_entry_point"),
                "status": MANUAL_SOURCE if (MANUAL_SOURCE := "MANUAL") else "MANUAL",
                "category_confidence": None,
                "candidate_medal": None,
                "current_effective_medal": "UNSCORED",
                "commercial_priority_score": None,
                "research_action": "MANUAL",
                "manual_by": m.get("reviewed_by"),
                "manual_at": str(m.get("reviewed_at") or ""),
                "manual_reason": m.get("manual_reason"),
            })
    except Exception:  # noqa: BLE001
        pass

    dossier["documents"] = _safe_di(
        """
        SELECT id, file_name, content_type, download_status, file_size_bytes,
               url, url IS NOT NULL AS has_url, local_path IS NOT NULL AS has_local,
               downloaded_at, local_deleted_at, retention_until, error_message
        FROM document_files
        WHERE procurement_id = %s
        ORDER BY id
        """,
        (int(procurement_id),),
    )

    dossier["findings"] = _safe_di(
        """
        SELECT d.id AS detail_id, d.category_code, d.matched_term,
               d.match_method, d.score,
               d.provenance_status, d.provenance_reason,
               d.matched_text, d.source_span, d.page_or_sheet, d.row_number,
               d.table_index, d.source_row_index, d.char_start, d.char_end,
               d.validation_status, f.file_name
        FROM document_match_details d
        JOIN document_matches m ON m.id = d.match_id
        JOIN document_files f ON f.id = m.file_id
        WHERE m.procurement_id = %s
        ORDER BY d.score DESC NULLS LAST, d.id
        LIMIT 300
        """,
        (int(procurement_id),),
    )

    # «Что можно поставить»: извлечённые структурированные сущности (с trust state).
    dossier["supply_candidates"] = _safe_di(
        """
        SELECT entity_type, product_name_raw, product_name_normalized,
               manufacturer_normalized, brand_normalized, model_article_normalized,
               quantity_value, quantity_unit_raw, unit_price_value, total_price_value,
               product_relation, source_quote, confidence, structured_fact_trust_state
        FROM structured_entities
        WHERE procurement_id = %s
        ORDER BY structured_fact_trust_state, total_price_value DESC NULLS LAST, id
        LIMIT 100
        """,
        (int(procurement_id),),
    )

    docs = dossier["documents"]
    finds = dossier["findings"]
    dossier["counts"] = {
        "documents": len(docs),
        "downloaded": sum(1 for d in docs if d.get("download_status") == "COMPLETED"),
        "downloadable": sum(
            1 for d in docs
            if d.get("has_url") and str(d.get("download_status") or "").upper() != "COMPLETED"
        ),
        "findings": len(finds),
        "verified": sum(1 for f in finds if f.get("provenance_status") == "VERIFIED"),
        "invalid": sum(1 for f in finds if f.get("provenance_status") == "INVALID"),
        "legacy_unverified": sum(
            1 for f in finds if f.get("provenance_status") == "LEGACY_UNVERIFIED"
        ),
        "opportunities": len(dossier["opportunities"]),
    }
    return dossier


SUPERUSER_PRIORITY = 32767  # max smallint priority_score
DEFAULT_QUEUE_PRIORITY = 50
PIPELINE_GENERATION = "S13_V4_EXHAUSTIVE_CONTEXT"
QUEUE_LANE = "crm_active_hot"
_ACTIVE_STATUSES = ("PENDING", "PRE_RESEARCH_WAITING", "PROCESSING")
_SKIP_STATUSES = ("PENDING", "PRE_RESEARCH_WAITING", "PROCESSING", "COMPLETED", "FAILED", "NO_LINKS")


def queue_procurement_for_documents(
    db: Any, procurement_id: int, *, superuser: bool = False, requested_by: str = "superuser"
) -> Dict[str, Any]:
    """Поставить закупку в документную очередь.

    ``superuser=True`` — «следующая после текущей»: максимальный
    ``priority_score`` (smallint max) среди PENDING/PRE_RESEARCH_WAITING.
    Никогда не трогает задачу в статусе PROCESSING. Работа с PROCESSING/терминальными
    статусами — вставка НОВОЙ попытки. Возвращает диагностический dict.
    """
    pid = int(procurement_id)
    proc = _safe(
        db, None,
        """SELECT source_table, source_id, contract_number FROM crm_procurements WHERE id = %s""",
        (pid,),
    )
    if not proc:
        return {"ok": False, "action": "procurement_not_found", "procurement_id": pid}
    p = proc[0]

    cats = _safe(
        db, None,
        """SELECT DISTINCT commercial_category_code FROM crm_procurement_category_opportunities
           WHERE procurement_id = %s AND status = 'CURRENT'""",
        (pid,),
    )
    category_codes = [str(c["commercial_category_code"]) for c in cats if c.get("commercial_category_code")]

    priority = SUPERUSER_PRIORITY if superuser else DEFAULT_QUEUE_PRIORITY
    context = {
        "populate_method": "SUPERUSER_MANUAL_QUEUE" if superuser else "MANUAL_QUEUE",
        "requested_by": requested_by,
        "superuser_priority": bool(superuser),
    }
    conn = None
    try:
        conn = _di_write_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, status FROM document_processing_queue
                   WHERE procurement_id = %s AND pipeline_generation = %s
                   ORDER BY id DESC LIMIT 1""",
                (pid, PIPELINE_GENERATION),
            )
            existing = cur.fetchone()
            if existing and str(existing[1]).upper() == "PROCESSING":
                return {
                    "ok": False, "action": "already_processing",
                    "procurement_id": pid, "queue_id": existing[0],
                }
            if existing and str(existing[1]).upper() in _ACTIVE_STATUSES:
                cur.execute(
                    """UPDATE document_processing_queue
                       SET status = 'PENDING',
                           priority_score = %s,
                           queue_lane = %s,
                           research_action = 'PRIORITY_DOCS',
                           category_context = COALESCE(category_context, '{}'::jsonb) || %s,
                           worker_id = NULL, started_at = NULL, completed_at = NULL,
                           last_error = NULL
                       WHERE id = %s""",
                    (priority, QUEUE_LANE, psycopg2.extras.Json(context), existing[0]),
                )
                return {
                    "ok": True, "action": "updated", "procurement_id": pid,
                    "queue_id": existing[0], "priority_score": priority,
                    "superuser": superuser,
                }
            cur.execute(
                """INSERT INTO document_processing_queue
                   (procurement_id, source_table, source_id, contract_number,
                    category_codes, category_context, candidate_level,
                    research_action, research_depth, queue_lane, priority_score,
                    status, pipeline_generation)
                   VALUES (%s,%s,%s,%s, %s,%s,%s, %s,%s,%s,%s, 'PENDING', %s)
                   RETURNING id""",
                (
                    pid, p.get("source_table") or "", p.get("source_id"),
                    p.get("contract_number"), category_codes,
                    psycopg2.extras.Json(context), None,
                    "PRIORITY_DOCS", "deep", QUEUE_LANE, priority,
                    PIPELINE_GENERATION,
                ),
            )
            new_id = cur.fetchone()[0]
        return {
            "ok": True, "action": "inserted", "procurement_id": pid,
            "queue_id": new_id, "priority_score": priority, "superuser": superuser,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("queue_procurement_for_documents failed pid=%s: %s", pid, exc)
        return {"ok": False, "action": "error", "procurement_id": pid, "error": str(exc)}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
