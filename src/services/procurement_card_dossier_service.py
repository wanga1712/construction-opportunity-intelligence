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

from src.services.section_projection_service import (
    RESIDUE_PREFIX,
    RESIDUE_ROWS_LIMIT,
    SECTION_MATERIALS_PER_SECTION,
    build_section_projection,
    projection_from_road,
)
from src.services.works_vs_goods_service import classify_fact_kind

logger = logging.getLogger("crm.procurement_card_dossier")

DI = "document_intelligence"
#: сколько строк отдаём road-шаблону для проекции карточки (2B.6.3)
ROAD_ROWS_LIMIT = 8000
#: Sheet-шаблоны (lighting/curbstone/drainage/flooring) читают больше строк:
#: крупные flooring-оценки содержат 16k+ позиций, и cap 8000 обрезал разделы.
SHEET_ROWS_LIMIT = 20000
#: сколько кандидатов берём из БД до фильтра «только товар» (WORKS_VS_GOODS)
SUPPLY_SQL_LIMIT = 300
#: сколько товарных кандидатов показываем в карточке
SUPPLY_ROWS_LIMIT = 100

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


def _record_error(errors: Optional[List[str]], label: str, exc: Exception) -> None:
    """Ошибка секции не глушится: она попадает в dossier['errors'] и видна в UI."""
    if errors is not None:
        errors.append("%s: %s: %s" % (label, type(exc).__name__, exc))


def _safe_di(sql: str, params: tuple = (), errors: Optional[List[str]] = None,
             label: str = "documents") -> List[Dict[str, Any]]:
    try:
        conn = _di_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in (cur.fetchall() or [])]
    except Exception as exc:  # noqa: BLE001
        logger.warning("dossier DI query failed: %s", exc)
        _record_error(errors, label, exc)
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


def _safe(db: Any, alias: Optional[str], sql: str, params: tuple = (),
          errors: Optional[List[str]] = None, label: str = "crm") -> List[Dict[str, Any]]:
    if db is None:
        _record_error(errors, label, RuntimeError("crm_db is None"))
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
        _record_error(errors, label, exc)
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
    errors: List[str] = dossier["errors"]

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
        errors=errors, label="identity",
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
        errors=errors, label="balance_holder",
    )
    dossier["parties"]["balance_holder"] = (
        balance[0].get("balance_holder") if balance else None
    )

    dossier["opportunities"] = _safe(
        db,
        None,
        """
        SELECT o.commercial_category_code, o.commercial_subcategory_code, o.opportunity_track,
               o.status, o.category_confidence, o.candidate_medal, o.current_effective_medal,
               o.commercial_priority_score, o.research_action,
               o.candidate_initial_score, o.candidate_initial_medal,
               o.confirmed_base_score, o.confirmed_base_medal,
               o.current_effective_score, o.current_effective_reason,
               (SELECT c.category_name FROM crm_product_categories c
                 WHERE c.category_code = o.commercial_category_code
                 ORDER BY c.id LIMIT 1) AS category_name
        FROM crm_procurement_category_opportunities o
        WHERE o.procurement_id = %s
        ORDER BY o.commercial_priority_score DESC NULLS LAST, o.commercial_category_code
        """,
        (int(procurement_id),),
        errors=errors, label="opportunities",
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
        errors=errors, label="scope",
    )
    dossier["scope"] = scope_rows[0] if scope_rows else {}
    # EMBEDDED_ESTIMATE_PARSE_FIRST_V1: object classification для сверки
    # раздела сметы с объектом закупки.
    _object_rows = _safe(
        db,
        None,
        """
        SELECT object_type, object_subtype, object_sector, application_area,
               classification_status, classification_source, confidence
          FROM crm_procurement_object_classifications
         WHERE procurement_id = %s AND is_current
         ORDER BY id DESC
         LIMIT 1
        """,
        (int(procurement_id),),
        errors=errors, label="object_classification",
    )
    dossier["object_classification"] = _object_rows[0] if _object_rows else {}
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
               downloaded_at, local_deleted_at, error_message
        FROM document_files
        WHERE procurement_id = %s
        ORDER BY id
        """,
        (int(procurement_id),),
        errors=errors, label="documents",
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
        errors=errors, label="findings",
    )

    # MATCH_TERM_HYGIENE_V1 / 3A source-filter: матчи из требований к заявке,
    # порядка/критериев оценки, протоколов и жалоб не являются коммерческими
    # фактами. Строки в БД не удаляем — скрываем только в карточке.
    try:
        from src.services.match_source_filter import (
            NON_RESEARCHABLE,
            classify_match_source,
        )

        _kept_findings = []
        _hidden_non_researchable = 0
        for _f in dossier["findings"]:
            _src = classify_match_source(_f.get("file_name"))
            _f["source_class"] = _src
            if _src == NON_RESEARCHABLE:
                _hidden_non_researchable += 1
                continue
            _kept_findings.append(_f)
        dossier["findings"] = _kept_findings
        dossier["findings_source_filter"] = {
            "hidden_non_researchable": _hidden_non_researchable,
        }
    except Exception as _exc:  # noqa: BLE001
        _record_error(errors, "findings_source_filter", _exc)

    # «Что можно поставить»: извлечённые структурированные сущности (с trust state).
    # STALE-SUPPRESSION (2B.6.2): у одной позиции может быть старая строка без
    # section-контекста и новая с ним. Показываем только предпочтительную:
    # приоритет `section_code IS NOT NULL`, затем больший `id`. Пары ищутся по
    # (procurement_id, source_document_id, row_or_line, product_name_raw): по
    # entity_fingerprint они НЕ совпадают (fingerprint включает page_or_sheet,
    # который появился только у новых строк). Физически строки не трогаем.
    dossier["supply_candidates"] = _safe_di(
        """
        WITH preferred AS (
            SELECT se.*,
                   row_number() OVER (
                       PARTITION BY se.procurement_id, se.source_document_id,
                                    coalesce(se.row_or_line, ''), coalesce(se.product_name_raw, '')
                       ORDER BY (se.section_code IS NOT NULL) DESC, se.id DESC
                   ) AS pref_rn
              FROM structured_entities se
             WHERE se.procurement_id = %s
        )
        SELECT se.entity_type, se.product_name_raw, se.product_name_normalized,
               se.manufacturer_normalized, se.brand_normalized, se.model_article_normalized,
               se.quantity_value, se.quantity_unit_raw, se.unit_price_value, se.total_price_value,
               se.product_relation, se.source_quote, se.confidence, se.structured_fact_trust_state,
               se.measurement_family, se.extractor_version,
               se.section_code, se.section_name, se.section_total_price_value,
               se.section_total_price_raw, se.section_total_source,
               se.page_or_sheet, se.row_or_line,
               COALESCE((
                 SELECT jsonb_agg(jsonb_build_object(
                          'name', a.attribute_name,
                          'name_normalized', a.attribute_name_normalized,
                          'raw_value', a.raw_value,
                          'normalized_value', a.normalized_value,
                          'numeric_value', a.numeric_value,
                          'unit', a.unit_normalized)
                        ORDER BY a.id)
                 FROM structured_attributes a WHERE a.entity_id = se.id), '[]'::jsonb) AS attributes
        FROM preferred se
        WHERE se.pref_rn = 1
        ORDER BY se.structured_fact_trust_state, se.total_price_value DESC NULLS LAST, se.id
        LIMIT 300
        """,
        (int(procurement_id),),
        errors=errors, label="supply_candidates",
    )

    # GOOD_SUPPLY_FACTS_V1: «что можно поставить» строится из чистого сервиса
    # (structured_entities + GOODS + qty/unit/total + цитата). Сырые
    # document_match_details здесь не участвуют — они остаются evidence.
    # DIRECT_SUPPLY не трогаем: у прямых поставок оставляем прежний набор кандидатов.
    _direct_track = any(
        str((o or {}).get("opportunity_track") or "").upper() == "DIRECT_SUPPLY"
        for o in (dossier.get("opportunities") or [])
    )
    dossier["supply_candidates_direct_untouched"] = bool(_direct_track)
    if not _direct_track:
        try:
            from src.services.good_supply_facts_service import build_good_supply_facts

            _supply = build_good_supply_facts(int(procurement_id))
            dossier["supply_candidates"] = _supply["facts"][:SUPPLY_ROWS_LIMIT]
            dossier["supply_audit"] = {
                "scanned": _supply["audit"]["scanned"],
                "kept": _supply["audit"]["kept"],
                "hidden_works": _supply["hidden_works"],
                "hidden_aggregates": _supply["hidden_aggregates"],
                "hidden_other": _supply["hidden_other"],
                "hidden_detail": _supply["hidden_detail"],
                "residue": _supply["residue"],
            }
            dossier["supply_candidates_works_hidden"] = _supply["hidden_works"]
        except Exception as _exc:  # чистый слой не должен ломать карточку
            _record_error(errors, "good_supply_facts", _exc)
            dossier["supply_candidates"] = []
            dossier["supply_audit"] = {"error": str(_exc)}

    # SECTION_LEVEL_NORMALIZATION_V1 (Phase 3): «раздел → сумма раздела → материалы»
    # + отдельный «остаток». Число показывается только для SECTION_TOTAL/COMPUTED_SUM;
    # COMPUTED_SUM_UNRELIABLE остаётся без подтверждённой суммы.
    _section_rows = _safe_di(
        """
        WITH ranked AS (
            SELECT se.section_code, se.section_name, se.page_or_sheet,
                   se.section_total_price_value, se.section_total_price_raw,
                   se.section_total_source, se.product_name_raw, se.product_name_normalized,
                   se.quantity_value, se.quantity_unit_raw, se.unit_price_value,
                   se.total_price_value, se.source_quote, se.row_or_line, se.layout_status,
                   count(*) OVER (PARTITION BY se.section_code) AS material_count,
                   count(*) FILTER (
                       WHERE se.entity_type = 'PRODUCT'
                         AND se.quantity_value IS NOT NULL
                         AND coalesce(se.quantity_unit_normalized, '') <> ''
                         AND se.quantity_unit_normalized NOT LIKE 'руб%%'
                         AND coalesce(se.product_name_normalized, se.product_name_raw, '')
                             !~* '^(итого|всего|стоимость|ндс|раздел|глава)'
                   ) OVER (PARTITION BY se.section_code) AS relevant_count,
                   row_number() OVER (
                       PARTITION BY se.section_code
                       ORDER BY se.total_price_value DESC NULLS LAST, se.id
                   ) AS rn
              FROM structured_entities se
             WHERE se.procurement_id = %s
               AND coalesce(se.section_code, '') <> ''
        )
        SELECT * FROM ranked WHERE rn <= %s ORDER BY section_code, rn
        """,
        (int(procurement_id), SECTION_MATERIALS_PER_SECTION),
        errors=errors, label="sections",
    )
    _residue_rows = _safe_di(
        """
        SELECT se.section_code, se.product_name_raw, se.product_name_normalized,
               se.quantity_value, se.quantity_unit_raw, se.unit_price_value,
               se.total_price_value, se.source_quote, se.row_or_line, se.layout_status
               , count(*) OVER () AS residue_total
          FROM structured_entities se
         WHERE se.procurement_id = %s
           AND se.extractor_version IS NOT NULL
           AND upper(se.section_code) LIKE %s
         ORDER BY se.total_price_value DESC NULLS LAST, se.id
         LIMIT %s
        """,
        (int(procurement_id), RESIDUE_PREFIX + "%", RESIDUE_ROWS_LIMIT),
        errors=errors, label="section_residue",
    )
    _residue_total = None
    if _residue_rows:
        try:
            _residue_total = int(_residue_rows[0].get("residue_total"))
        except (TypeError, ValueError):
            _residue_total = None
    dossier["section_projection"] = build_section_projection(
        _section_rows, _residue_rows, residue_total=_residue_total
    )

    # 2B.6.3: дорожные закупки показываем через road-projection, остальные — generic.
    # Признак дорожной формы — найденные маркеры «Итого по разделу N» / «Глава N».
    dossier["section_projection_source"] = "embedded_extraction"
    try:
        _road_rows = _safe_di(
            """
            WITH preferred AS (
                SELECT se.*,
                       row_number() OVER (
                           PARTITION BY se.procurement_id, se.source_document_id,
                                        coalesce(se.row_or_line, ''),
                                        coalesce(se.product_name_raw, '')
                           ORDER BY (se.section_code IS NOT NULL) DESC, se.id DESC
                       ) AS pref_rn
                  FROM structured_entities se
                 WHERE se.procurement_id = %s
            )
            SELECT se.product_name_raw, se.product_name_normalized, se.entity_type,
                   se.quantity_value, se.quantity_unit_normalized, se.quantity_unit_raw,
                   se.unit_price_value, se.total_price_value, se.source_quote, se.row_or_line,
                   se.layout_status, se.page_or_sheet, se.section_code
              FROM preferred se
             WHERE se.pref_rn = 1
             ORDER BY se.id
             LIMIT %s
            """,
            (int(procurement_id), ROAD_ROWS_LIMIT),
            errors=errors, label="road_rows",
        )
        if _road_rows:
            from tender_documents_research.document_processor.road_repair_section_templates import (
                build_road_sections,
            )

            _road = build_road_sections(_road_rows)
            # Признак дорожной формы — маркеры уровня РАЗДЕЛА с материалами
            # («Итого по разделу N <Название>»). Одних «Глава N» мало: их носят и
            # нерoad-сметы (напр. 148391), для которых generic-проекция полезнее.
            _road_confident = any(
                int(s.get("material_count") or 0) > 0 and s.get("marker_kind") == "razdel"
                for s in _road.get("sections") or []
            )
            if _road_confident:
                dossier["section_projection"] = projection_from_road(_road)
                dossier["section_projection_source"] = "road_repair_section_templates"
    except Exception as _exc:  # дорожная проекция не должна ломать карточку
        _record_error(errors, "road_projection", _exc)

    # LIGHTING_SECTION_TEMPLATES_V1 (3A Phase 2): если CURRENT-возможность
    # lighting и дорожный шаблон не дал уверенных разделов — пробуем
    # светотехнический маркер «Раздел/Глава/Секция N <Название>».
    # Раздел — контейнер материалов; total не обязателен.
    _has_lighting = any(
        str((o or {}).get("commercial_category_code") or "") == "lighting"
        for o in (dossier.get("opportunities") or [])
    )
    if _has_lighting and dossier.get("section_projection_source") != "road_repair_section_templates":
        try:
            from tender_documents_research.document_processor.lighting_section_templates import (
                build_lighting_sections,
            )

            _lighting_rows = _safe_di(
                """
                WITH preferred AS (
                    SELECT se.*,
                           row_number() OVER (
                               PARTITION BY se.procurement_id, se.source_document_id,
                                            coalesce(se.row_or_line, ''),
                                            coalesce(se.product_name_raw, '')
                               ORDER BY (se.section_code IS NOT NULL) DESC, se.id DESC
                           ) AS pref_rn
                      FROM structured_entities se
                     WHERE se.procurement_id = %s
                       AND se.category_code = 'lighting'
                )
                SELECT se.product_name_raw, se.product_name_normalized, se.entity_type,
                       se.quantity_value, se.quantity_unit_normalized, se.quantity_unit_raw,
                       se.unit_price_value, se.total_price_value, se.source_quote,
                       se.row_or_line, se.layout_status, se.page_or_sheet, se.section_code,
                       se.source_document_id
                  FROM preferred se
                 WHERE se.pref_rn = 1
                 ORDER BY se.id
                 LIMIT %s
                """,
                (int(procurement_id), SHEET_ROWS_LIMIT),
                errors=errors, label="lighting_rows",
            )
            if _lighting_rows:
                _lighting = build_lighting_sections(_lighting_rows)
                _lighting_confident = any(
                    int(s.get("material_count") or 0) > 0
                    for s in _lighting.get("sections") or []
                )
                if _lighting_confident:
                    dossier["section_projection"] = projection_from_road(_lighting)
                    dossier["section_projection_source"] = "lighting_section_templates"
                    dossier["lighting_template"] = {
                        "sections": len(_lighting.get("sections") or []),
                        "residue": (_lighting.get("residue") or {}).get("count"),
                    }
        except Exception as _exc:  # noqa: BLE001
            _record_error(errors, "lighting_projection", _exc)

    # CURBSTONE_SECTION_TEMPLATES_V1 (3A Phase 2): маркеры «Раздел/Глава/
    # Секция/Участок/Лот»; fallback — лист/страница OCR-оценки. Пустые
    # контейнеры и строки без страницы честно остаются в RESIDUE.
    _has_curbstone = any(
        str((o or {}).get("commercial_category_code") or "") == "curbstone"
        for o in (dossier.get("opportunities") or [])
    )
    if _has_curbstone and dossier.get("section_projection_source") not in (
        "road_repair_section_templates", "lighting_section_templates",
    ):
        try:
            from tender_documents_research.document_processor.curbstone_section_templates import (
                build_curbstone_sections,
            )

            _curb_rows = _safe_di(
                """
                WITH preferred AS (
                    SELECT se.*,
                           row_number() OVER (
                               PARTITION BY se.procurement_id, se.source_document_id,
                                            coalesce(se.row_or_line, ''),
                                            coalesce(se.product_name_raw, '')
                               ORDER BY (se.section_code IS NOT NULL) DESC, se.id DESC
                           ) AS pref_rn
                      FROM structured_entities se
                     WHERE se.procurement_id = %s
                       AND se.category_code = 'curbstone'
                )
                SELECT se.product_name_raw, se.product_name_normalized, se.entity_type,
                       se.quantity_value, se.quantity_unit_normalized, se.quantity_unit_raw,
                       se.unit_price_value, se.total_price_value, se.source_quote,
                       se.row_or_line, se.layout_status, se.page_or_sheet, se.section_code,
                       se.source_document_id
                  FROM preferred se
                 WHERE se.pref_rn = 1
                 ORDER BY se.id
                 LIMIT %s
                """,
                (int(procurement_id), SHEET_ROWS_LIMIT),
                errors=errors, label="curbstone_rows",
            )
            if _curb_rows:
                _curb = build_curbstone_sections(_curb_rows)
                _curb_confident = any(
                    int(s.get("material_count") or 0) > 0
                    for s in _curb.get("sections") or []
                )
                if _curb_confident:
                    dossier["section_projection"] = projection_from_road(_curb)
                    dossier["section_projection_source"] = "curbstone_section_templates"
                    dossier["curbstone_template"] = {
                        "sections": len(_curb.get("sections") or []),
                        "residue": (_curb.get("residue") or {}).get("count"),
                    }
        except Exception as _exc:  # noqa: BLE001
            _record_error(errors, "curbstone_projection", _exc)

    # DRAINAGE_SECTION_TEMPLATES_V1 (3A Phase 2): маркеры (если появятся) +
    # page_or_sheet fallback для OCR/xlsx-оценок; честный RESIDUE.
    _has_drainage = any(
        str((o or {}).get("commercial_category_code") or "") == "drainage_water_management"
        for o in (dossier.get("opportunities") or [])
    )
    if _has_drainage and dossier.get("section_projection_source") not in (
        "road_repair_section_templates", "lighting_section_templates",
        "curbstone_section_templates",
    ):
        try:
            from tender_documents_research.document_processor.drainage_section_templates import (
                build_drainage_sections,
            )

            _dr_rows = _safe_di(
                """
                WITH preferred AS (
                    SELECT se.*,
                           row_number() OVER (
                               PARTITION BY se.procurement_id, se.source_document_id,
                                            coalesce(se.row_or_line, ''),
                                            coalesce(se.product_name_raw, '')
                               ORDER BY (se.section_code IS NOT NULL) DESC, se.id DESC
                           ) AS pref_rn
                      FROM structured_entities se
                     WHERE se.procurement_id = %s
                       AND se.category_code = 'drainage_water_management'
                )
                SELECT se.product_name_raw, se.product_name_normalized, se.entity_type,
                       se.quantity_value, se.quantity_unit_normalized, se.quantity_unit_raw,
                       se.unit_price_value, se.total_price_value, se.source_quote,
                       se.row_or_line, se.layout_status, se.page_or_sheet, se.section_code,
                       se.source_document_id
                  FROM preferred se
                 WHERE se.pref_rn = 1
                 ORDER BY se.id
                 LIMIT %s
                """,
                (int(procurement_id), SHEET_ROWS_LIMIT),
                errors=errors, label="drainage_rows",
            )
            if _dr_rows:
                _dr = build_drainage_sections(_dr_rows)
                _dr_confident = any(
                    int(s.get("material_count") or 0) > 0
                    for s in _dr.get("sections") or []
                )
                if _dr_confident:
                    dossier["section_projection"] = projection_from_road(_dr)
                    dossier["section_projection_source"] = "drainage_section_templates"
                    dossier["drainage_template"] = {
                        "sections": len(_dr.get("sections") or []),
                        "residue": (_dr.get("residue") or {}).get("count"),
                    }
        except Exception as _exc:  # noqa: BLE001
            _record_error(errors, "drainage_projection", _exc)

    # FLOORING_SECTION_TEMPLATES_V1 (3A Phase 2): маркеры + page_or_sheet
    # fallback через общий sheet-движок; честный RESIDUE.
    _has_flooring = any(
        str((o or {}).get("commercial_category_code") or "") == "flooring"
        for o in (dossier.get("opportunities") or [])
    )
    if _has_flooring and dossier.get("section_projection_source") not in (
        "road_repair_section_templates", "lighting_section_templates",
        "curbstone_section_templates", "drainage_section_templates",
    ):
        try:
            from tender_documents_research.document_processor.flooring_section_templates import (
                build_flooring_sections,
            )

            _fl_rows = _safe_di(
                """
                WITH preferred AS (
                    SELECT se.*,
                           row_number() OVER (
                               PARTITION BY se.procurement_id, se.source_document_id,
                                            coalesce(se.row_or_line, ''),
                                            coalesce(se.product_name_raw, '')
                               ORDER BY (se.section_code IS NOT NULL) DESC, se.id DESC
                           ) AS pref_rn
                      FROM structured_entities se
                     WHERE se.procurement_id = %s
                       AND se.category_code = 'flooring'
                )
                SELECT se.product_name_raw, se.product_name_normalized, se.entity_type,
                       se.quantity_value, se.quantity_unit_normalized, se.quantity_unit_raw,
                       se.unit_price_value, se.total_price_value, se.source_quote,
                       se.row_or_line, se.layout_status, se.page_or_sheet, se.section_code,
                       se.source_document_id
                  FROM preferred se
                 WHERE se.pref_rn = 1
                 ORDER BY se.id
                 LIMIT %s
                """,
                (int(procurement_id), SHEET_ROWS_LIMIT),
                errors=errors, label="flooring_rows",
            )
            if _fl_rows:
                _fl = build_flooring_sections(_fl_rows)
                _fl_confident = any(
                    int(s.get("material_count") or 0) > 0
                    for s in _fl.get("sections") or []
                )
                if _fl_confident:
                    dossier["section_projection"] = projection_from_road(_fl)
                    dossier["section_projection_source"] = "flooring_section_templates"
                    dossier["flooring_template"] = {
                        "sections": len(_fl.get("sections") or []),
                        "residue": (_fl.get("residue") or {}).get("count"),
                    }
        except Exception as _exc:  # noqa: BLE001
            _record_error(errors, "flooring_projection", _exc)

    # PROCUREMENT_CARD_CATEGORY_PIPELINE_V1: read-model вкладки «Категории».
    # Одна opportunity = один блок; медали — существующие authority-поля.
    dossier["categories"] = []
    try:
        from src.services.document_queue_progress_service import load_queue_progress
        from src.services.procurement_card_category_service import (
            build_category_cards,
            load_extraction_outcomes,
            load_model_validation_counts,
        )

        _progress = load_queue_progress([int(procurement_id)])
        _model_counts: Dict[str, Any] = {}
        _outcomes: Dict[str, Any] = {}
        try:
            _model_counts = load_model_validation_counts(int(procurement_id))
        except Exception as _exc:  # noqa: BLE001
            _record_error(errors, "category_model_counts", _exc)
        try:
            _outcomes = load_extraction_outcomes(int(procurement_id))
        except Exception as _exc:  # noqa: BLE001
            _record_error(errors, "category_extraction_outcomes", _exc)
        dossier["categories"] = build_category_cards(
            opportunities=dossier["opportunities"],
            supply_facts=dossier.get("supply_candidates") or [],
            documents=dossier["documents"],
            queue_progress=_progress,
            procurement_id=int(procurement_id),
            model_counts=_model_counts,
            extraction_outcomes=_outcomes,
            procurement_title=(dossier.get("identity") or {}).get("auction_name"),
            okpd_name=(dossier.get("identity") or {}).get("okpd_name"),
            object_class=" ".join(filter(None, [
                (dossier.get("object_classification") or {}).get("object_type"),
                (dossier.get("object_classification") or {}).get("object_subtype"),
                (dossier.get("object_classification") or {}).get("object_sector"),
                (dossier.get("object_classification") or {}).get("application_area"),
            ])),
        )
    except Exception as _exc:  # noqa: BLE001
        _record_error(errors, "categories", _exc)

    # EMBEDDED_ESTIMATE_PARSE_FIRST_V1: сравнение разделов сметы с закупкой.
    try:
        from src.services.object_section_match_service import compare_sections

        _ident = dossier.get("identity") or {}
        dossier["object_section_matches"] = compare_sections(
            (dossier.get("section_projection") or {}).get("sections") or [],
            procurement_title=_ident.get("auction_name"),
            okpd_name=_ident.get("okpd_name"),
            object_class=" ".join(filter(None, [
                (dossier.get("object_classification") or {}).get("object_type"),
                (dossier.get("object_classification") or {}).get("object_subtype"),
                (dossier.get("object_classification") or {}).get("object_sector"),
                (dossier.get("object_classification") or {}).get("application_area"),
            ])),
        )
    except Exception as _exc:  # noqa: BLE001
        _record_error(errors, "object_section_matches", _exc)

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
        "categories": len(dossier.get("categories") or []),
        "confirmed_categories": sum(
            1 for c in (dossier.get("categories") or [])
            if c.get("confirmed_base_medal")
        ),
        "findings_hidden_non_researchable": (
            dossier.get("findings_source_filter") or {}
        ).get("hidden_non_researchable", 0),
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
