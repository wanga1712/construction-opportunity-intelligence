"""Mode-aware analytics table workspace (V1.1 data layer).

Read-only. Builds one manager-facing row per ``procurement x category`` with a
commerce-first column set that depends on the procurement mode, plus the
temporal submission-window view (deadline, consumed ratio, temporal bucket and
the next real downgrade). No medal logic is changed here; the temporal policy
comes from the canonical helper ``submission_window_temporal``.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from src.services.commercial_routing_v3.submission_window_temporal import (
    FRESH,
    SILVER_CAP,
    BRONZE_CAP,
    WOOD_CAP,
    EXPIRED,
    TEMPORAL_UNKNOWN,
    compute_submission_window,
    format_seconds,
)
from src.services.commercial_routing_v3.category_hard_veto import hard_veto_reason

# ── Procurement modes / layouts ──────────────────────────────────────────────
DIRECT_SUPPLY = "DIRECT_SUPPLY"
EMBEDDED_MATERIAL = "EMBEDDED_MATERIAL"
DESIGN = "DESIGN"
OBJECT = "OBJECT"
ALL_MODES = "ALL"

MODE_LABELS = {
    DIRECT_SUPPLY: "Прямая поставка",
    EMBEDDED_MATERIAL: "В составе работ",
    DESIGN: "Проект / влияние",
    OBJECT: "Объект (проект)",
    ALL_MODES: "Все режимы",
}

# Layouts are ordered column ids; single source of truth for mode-aware columns.
LAYOUTS: Dict[str, Sequence[str]] = {
    DIRECT_SUPPLY: (
        "medal", "purchase", "product", "customer", "price",
        "deadline", "temporal", "delivery", "documents", "status", "queue", "source", "region",
    ),
    EMBEDDED_MATERIAL: (
        "medal", "purchase", "product", "object", "works",
        "price", "deadline", "temporal", "delivery", "status", "documents", "queue",
    ),
    DESIGN: (
        "medal", "purchase", "product", "object", "works",
        "price", "deadline", "temporal", "delivery", "status", "documents", "queue",
    ),
    OBJECT: (
        "medal", "purchase", "product", "object", "works",
        "price", "deadline", "temporal", "delivery", "status", "documents", "queue",
    ),
    # Mixed selection: one context column instead of two empty ones.
    ALL_MODES: (
        "medal", "purchase", "product", "mode", "context",
        "price", "deadline", "temporal", "delivery", "status", "documents", "queue",
    ),
}

COLUMN_LABELS = {
    "medal": "Медаль",
    "purchase": "Закупка",
    "product": "Товар",
    "customer": "Заказчик",
    "price": "НМЦК",
    "deadline": "Подача до",
    "temporal": "Временное окно",
    "delivery": "Поставка",
    "documents": "Документы",
    "status": "Статус",
    "queue": "Очередь",
    "source": "Источник",
    "region": "Регион",
    "object": "Объект",
    "works": "Работы",
    "mode": "Режим",
    "context": "Контекст",
}

_BUCKET_COLORS = {
    FRESH: "#2e9e4f", SILVER_CAP: "#d4b106", BRONZE_CAP: "#e8710a",
    WOOD_CAP: "#c62828", EXPIRED: "#7f1d1d", TEMPORAL_UNKNOWN: "#b0b4bb",
}
_BUCKET_LABELS = {
    FRESH: "FRESH", SILVER_CAP: "CAP: SILVER", BRONZE_CAP: "CAP: BRONZE",
    WOOD_CAP: "WOOD", EXPIRED: "EXPIRED", TEMPORAL_UNKNOWN: "Срок неизвестен",
}
_STAGE_LABELS = {
    "torgi": "Идут торги",
    "commission": "Комиссия",
    "razygranye": "Разыграна",
}

# Direct supply dominates the commercial mix; embedded/project are weighted down.
MODE_WEIGHT = {DIRECT_SUPPLY: 1.0, EMBEDDED_MATERIAL: 0.55, DESIGN: 0.6, "": 0.4}


def mode_weight(track: Any) -> float:
    return MODE_WEIGHT.get(mode_for_track(track), 0.4)


def bucket_color(bucket: str) -> str:
    return _BUCKET_COLORS.get(bucket, "#9e9e9e")


def bucket_label(bucket: str) -> str:
    return _BUCKET_LABELS.get(bucket, bucket)


def mode_for_track(track: Any) -> str:
    value = str(track or "").upper()
    if value == "DIRECT_SUPPLY":
        return DIRECT_SUPPLY
    if value == "EMBEDDED_MATERIAL":
        return EMBEDDED_MATERIAL
    if value in ("DESIGN_REQUIREMENT", "DESIGN_INFLUENCE"):
        return DESIGN
    return ""


def layout_for(selected_mode: str) -> Sequence[str]:
    return LAYOUTS.get(selected_mode or ALL_MODES, LAYOUTS[ALL_MODES])


def _clean(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text or text.lower() in {"none", "null", "unknown", "unassessed", "—", "nan"}:
        return None
    return text


def _amount(value: Any) -> Optional[str]:
    """NULL / missing -> '—'. A non-positive value reads as missing, never '0 ₽'."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f} млн ₽"
    if number >= 1_000:
        return f"{number / 1_000:.1f} тыс ₽"
    return f"{number:,.0f} ₽".replace(",", " ")


def _fmt_deadline(value: Any, now: datetime) -> Optional[str]:
    dt = _parse_dt(value)
    if dt is None:
        return None
    local = dt.astimezone(timezone.utc)
    head = local.strftime("%d.%m")
    day = local.date()
    if day == now.date():
        head = "Сегодня"
    elif day == (now + timedelta(days=1)).date():
        head = "Завтра"
    has_time = bool(str(value).strip()) and ("T" in str(value) or " " in str(value))
    return f"{head} · {local.strftime('%H:%M')}" if has_time else head


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        if "T" in text or " " in text:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        d = date.fromisoformat(text[:10])
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    except ValueError:
        return None


def _law_label(source_table: Any) -> Optional[str]:
    try:
        from src.services.source_contour import resolve_source_contour
        contour = resolve_source_contour(source_table) or {}
        return _clean(contour.get("card_primary"))
    except Exception:
        return None


def _documents_text(raw: Dict[str, Any]) -> str:
    best = 0
    for key in ("file_count", "document_link_count"):
        try:
            best = max(best, int(raw.get(key) or 0))
        except (TypeError, ValueError):
            continue
    return f"{best} ✓" if best > 0 else "—"


def _canonical_window(raw: Dict[str, Any]) -> tuple:
    """Mirror canonical_card OPEN procedure-window derivation.

    For non-awarded procurements the canonical pre-model card derives the
    submission window from ``submission_start_at``/``submission_deadline_at``
    and falls back to the EIS procedure dates ``start_date``/``end_date``.
    Awarded rows keep only explicit submission timestamps (contract dates are
    never reused as a submission window).
    """
    stage = str(raw.get("crm_stage") or "").lower()
    awarded = stage in ("razygranye",) or str(raw.get("award_status") or "").startswith("awarded")
    start = raw.get("submission_start_at")
    deadline = raw.get("submission_deadline_at")
    if not awarded:
        start = start or raw.get("start_date")
        deadline = deadline or raw.get("end_date")
    return start, deadline


def build_row(raw: Dict[str, Any], *, now: datetime) -> Dict[str, Any]:
    """Map one raw procurement x category row into the manager view model."""
    mode = mode_for_track(raw.get("opportunity_track"))
    stage = str(raw.get("crm_stage") or "").lower()
    med_cur = _clean(raw.get("current_effective_medal"))
    med_init = _clean(raw.get("candidate_initial_medal"))
    baseline = med_init or med_cur
    delivery_start_raw = raw.get("delivery_start_date")
    delivery_end_raw = raw.get("delivery_end_date")
    delivery_available = bool(delivery_start_raw) and bool(delivery_end_raw)
    window_start, window_deadline = _canonical_window(raw)
    torgi_view = compute_submission_window(
        submission_start_at=window_start,
        submission_deadline_at=window_deadline,
        baseline_medal=baseline,
        now=now,
    )
    # Delivery window is the live clock when torgi is over (awarded object/project)
    # OR when there is no usable torgi window but delivery dates exist.
    delivery_clock = delivery_available and (
        (mode in (EMBEDDED_MATERIAL, DESIGN) and stage == "razygranye")
        or torgi_view.get("temporal_state") == "UNKNOWN"
    )
    if delivery_clock:
        window_start, window_deadline = delivery_start_raw, delivery_end_raw
        temporal = compute_submission_window(
            submission_start_at=window_start,
            submission_deadline_at=window_deadline,
            baseline_medal=baseline,
            now=now,
        )
        temporal["window_basis"] = "DELIVERY"
    else:
        temporal = torgi_view
    # Dates parsed before the 2026-08-16 tag fix are not a real submission window
    # (they came from documentationDelivery). Never present them as a live bar.
    if str(raw.get("deadline_trust") or "").upper() == "UNRECOVERABLE_LEGACY":
        from src.services.commercial_routing_v3.submission_window_temporal import (
            TEMPORAL_UNKNOWN as _UNK,
        )
        temporal = dict(temporal)
        temporal.update(temporal_bucket=_UNK, window_consumed_ratio=None,
                        next_degrade_medal=None, seconds_to_next_degrade=None,
                        seconds_to_wood=None, untrusted=True)
    deadline_text = _fmt_deadline(window_deadline, now)
    if not deadline_text:
        deadline_text = "—"
    state = temporal["temporal_state"]
    if temporal.get("untrusted"):
        remaining_text = "дата не подтверждена"
    elif state == "EXPIRED":
        remaining_text = "Подача завершена"
    elif state == "UNKNOWN":
        # Deadline may still be known even when the full window is not.
        remaining_text = "Срок не определён" if deadline_text == "—" else "окно не определено"
    else:
        remaining_text = f"осталось {format_seconds(temporal.get('seconds_to_deadline'))}"

    object_text = _clean(raw.get("object_type")) or "—"
    works_text = _clean(raw.get("object_context")) or "—"
    context_text = "—"
    if mode in (EMBEDDED_MATERIAL, DESIGN):
        parts = [p for p in (_clean(raw.get("object_type")), _clean(raw.get("object_context"))) if p]
        context_text = " · ".join(parts) or "—"

    law = _law_label(raw.get("source_table"))
    purchase_meta = " · ".join(
        p for p in (f"№ {raw['contract_number']}" if _clean(raw.get("contract_number")) else None, law) if p
    ) or None
    product_primary = _clean(raw.get("subcategory_name")) or "—"
    category_text = _clean(raw.get("category_name")) or _clean(raw.get("commercial_category_code"))
    if product_primary == "—" and category_text:
        product_primary = category_text  # subcategory missing -> show the category
    product_secondary = _clean(raw.get("product_name"))
    if product_secondary and product_secondary == product_primary:
        product_secondary = None  # never repeat the subcategory as the product
    if product_secondary is None and category_text and category_text != product_primary:
        product_secondary = category_text  # always show which category the row belongs to

    delivery_start = _fmt_day(raw.get("delivery_start_date"))
    delivery_end = _fmt_day(raw.get("delivery_end_date"))
    if delivery_start and delivery_end:
        delivery_text = f"{delivery_start} – {delivery_end}"
    elif delivery_end:
        delivery_text = f"до {delivery_end}"
    elif delivery_start:
        delivery_text = f"с {delivery_start}"
    else:
        delivery_text = "—"

    status_text = _STAGE_LABELS.get(stage, _clean(raw.get("crm_stage")) or "—")
    if delivery_clock:
        status_text = "Идёт поставка"

    # Medal must never look better than the temporal window allows (no GOLD at CAP: BRONZE).
    from src.services.commercial_routing_v3.submission_window_temporal import (
        MEDAL_RANK,
        medal_cap_for_bucket,
    )
    capped_from = None
    cap_medal = medal_cap_for_bucket(temporal.get("temporal_bucket") or "")
    if cap_medal and med_cur:
        if MEDAL_RANK.get(cap_medal, 9) < MEDAL_RANK.get(str(med_cur).upper(), 9):
            capped_from = med_cur
            med_cur = cap_medal

    return {
        "procurement_id": raw.get("procurement_id"),
        "mode": mode,
        "category_code": raw.get("commercial_category_code"),
        "veto_reason": hard_veto_reason(
            raw.get("commercial_category_code"), raw.get("auction_name"), raw.get("okpd_name")
        ),
        "medal_current": med_cur or "—",
        "medal_capped_from": capped_from,
        # Подтверждённая медаль: временной кап её не понижает, он показывается отдельно.
        "medal_confirmed": capped_from or med_cur or "—",
        "medal_initial": med_init,
        "medal_downgraded": bool(med_cur and med_init and med_cur != med_init),
        "purchase_title": _clean(raw.get("auction_name")) or "—",
        "purchase_meta": purchase_meta,
        "product_primary": product_primary,
        "product_secondary": product_secondary,
        "customer": _clean(raw.get("customer")) or "—",
        "file_count": raw.get("file_count"),
        "evidence_count": raw.get("evidence_count"),
        "price_text": _amount(raw.get("initial_price")) or "—",
        "object_text": object_text,
        "works_text": works_text,
        "context_text": context_text,
        "region": _clean(raw.get("delivery_region")) or "—",
        "source_text": law or _clean(raw.get("source_table")) or "—",
        "status_text": status_text,
        "documents_text": _documents_text(raw),
        "queue_text": "—",
        "deadline_text": deadline_text,
        "remaining_text": remaining_text,
        "torgi_start_text": _fmt_day(window_start) or "—",
        "delivery_text": delivery_text,
        "temporal": temporal,
    }


def _fmt_day(value: Any) -> Optional[str]:
    dt = _parse_dt(value)
    return dt.strftime("%d.%m.%y") if dt else None


def build_workspace_rows(
    raw_rows: Sequence[Dict[str, Any]], *, selected_mode: str = ALL_MODES,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    rows = [build_row(raw, now=now) for raw in raw_rows]
    rows.sort(key=_row_sort_key)
    return {"columns": list(layout_for(selected_mode)), "rows": rows, "selected_mode": selected_mode}


def _row_sort_key(row: Dict[str, Any]):
    """Приоритет показа (WIP): сначала карточки с распарсенными документами и
    подтверждёнными категориями, затем медаль (GOLD→…), затем свежесть окна,
    затем статус (сначала «идут торги», потом «разыграна»)."""
    from src.services.commercial_routing_v3.submission_window_temporal import (
        BRONZE_CAP,
        EXPIRED,
        FRESH,
        MEDAL_RANK,
        SILVER_CAP,
        TEMPORAL_UNKNOWN,
        WOOD_CAP,
    )
    # Сортировка и заголовок группы — по подтверждённой медали: закупка GOLD с
    # исчерпанным окном не должна проваливаться в самый низ, её «кап» показывается отдельно.
    medal = str(row.get("medal_confirmed") or row.get("medal_current") or "").upper()
    temporal = row.get("temporal") or {}
    bucket = str(temporal.get("temporal_bucket") or TEMPORAL_UNKNOWN).upper()
    # «Есть данные»: реально скачанные документы или найденные подтверждения,
    # а не number of links в card_json (он у многих 0 при живых документах).
    try:
        files_n = int(row.get("file_count") or 0)
    except (TypeError, ValueError):
        files_n = 0
    try:
        evid_n = int(row.get("evidence_count") or 0)
    except (TypeError, ValueError):
        evid_n = 0
    has_docs = files_n > 0 or evid_n > 0
    bucket_rank = {
        FRESH: 0, SILVER_CAP: 1, BRONZE_CAP: 2, WOOD_CAP: 3, EXPIRED: 4,
    }.get(bucket, 5)
    status = str(row.get("status_text") or "")
    stage_rank = 0 if status.startswith("Идут торги") else (1 if "Разыгран" in status else 2)
    deadline = temporal.get("submission_deadline_at") or "9999"
    return (
        -MEDAL_RANK.get(medal, -1),
        0 if has_docs else 1,
        bucket_rank,
        stage_rank,
        str(deadline),
    )


_SQL_BASE = """
    SELECT DISTINCT ON (o.procurement_id, o.commercial_category_code, o.commercial_subcategory_code, o.opportunity_track)
        o.procurement_id,
        p.auction_name,
        p.contract_number,
        p.initial_price,
        p.customer,
        p.file_count,
        p.evidence_count,
        p.delivery_region,
        p.okpd_code,
        p.okpd_name,
        p.crm_stage,
        p.source_table,
        p.deadline_trust,
        p.start_date,
        p.end_date,
        p.delivery_start_date,
        p.delivery_end_date,
        o.opportunity_track,
        o.commercial_category_code,
        o.commercial_subcategory_code,
        s.subcategory_name,
        cat.category_name,
        o.candidate_initial_medal,
        o.current_effective_medal,
        oc.object_type,
        oc.object_context,
        cc.card_json ->> 'submission_start_at' AS submission_start_at,
        cc.card_json ->> 'submission_deadline_at' AS submission_deadline_at,
        cc.card_json ->> 'document_link_count' AS document_link_count
    FROM crm_procurement_category_opportunities o
    JOIN crm_procurements p ON p.id = o.procurement_id
    LEFT JOIN crm_product_subcategories s
      ON s.subcategory_code = o.commercial_subcategory_code
     AND s.category_id = (
            SELECT c.id FROM crm_product_categories c
            WHERE c.category_code = o.commercial_category_code
            ORDER BY c.id LIMIT 1
        )
    LEFT JOIN crm_procurement_object_classifications oc
      ON oc.procurement_id = p.id AND oc.is_current
    LEFT JOIN crm_product_categories cat ON cat.category_code = o.commercial_category_code
    LEFT JOIN crm_v3_canonical_procurement_cards cc
      ON cc.procurement_id = p.id
    WHERE o.status = 'CURRENT'
"""


def _mode_sql(mode: str) -> tuple[str, tuple]:
    if mode == DIRECT_SUPPLY:
        return " AND o.opportunity_track = %s", (DIRECT_SUPPLY,)
    if mode == EMBEDDED_MATERIAL:
        return " AND o.opportunity_track = %s", (EMBEDDED_MATERIAL,)
    if mode == OBJECT:
        return " AND o.opportunity_track IN ('EMBEDDED_MATERIAL', 'DESIGN_REQUIREMENT', 'DESIGN_INFLUENCE')", ()
    if mode == DESIGN:
        return " AND o.opportunity_track IN ('DESIGN_REQUIREMENT', 'DESIGN_INFLUENCE')", ()
    return "", ()


def load_workspace_rows(
    crm_db: Any, *, selected_mode: str = ALL_MODES, category_code: Optional[str] = None,
    subcategory_code: Optional[str] = None, object_type: Optional[str] = None,
    region: Optional[str] = None, search_text: Optional[str] = None,
    only_active: bool = True, limit: int = 200, now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Read-only load of the workspace rows for a mode and optional category."""
    if crm_db is None:
        return {"columns": list(layout_for(selected_mode)), "rows": [], "selected_mode": selected_mode, "error": None}
    where, params = _mode_sql(selected_mode)
    sql = _SQL_BASE + where
    parameters: List[Any] = list(params)
    if category_code:
        sql += " AND o.commercial_category_code = %s"
        parameters.append(category_code)
    # Direct supply that already traded out is dead weight: keep only live rows.
    if only_active and selected_mode == DIRECT_SUPPLY:
        sql += " AND (p.end_date IS NULL OR p.end_date >= current_date)"
    if subcategory_code and subcategory_code != "__all__":
        if subcategory_code == "__unclassified__":
            sql += " AND o.commercial_subcategory_code IS NULL"
        else:
            sql += " AND o.commercial_subcategory_code = %s"
            parameters.append(subcategory_code)
    if object_type:
        sql += " AND oc.object_type = %s"
        parameters.append(object_type)
    if region:
        sql += " AND p.delivery_region = %s"
        parameters.append(region)
    if search_text:
        sql += " AND (p.auction_name ILIKE %s OR p.contract_number ILIKE %s OR p.customer ILIKE %s)"
        token = f"%{search_text.strip()}%"
        parameters.extend([token, token, token])
    # Внутренний ORDER BY обязателен для DISTINCT ON; приоритет показа —
    # внешним ORDER BY, иначе окно берёт первые procid и витрина начинается с BRONZE/WOOD.
    inner = sql + (" ORDER BY o.procurement_id, o.commercial_category_code,"
                   " o.commercial_subcategory_code, o.opportunity_track, o.id DESC")
    sql = (
        "SELECT * FROM (" + inner + ") t ORDER BY "
        "CASE upper(coalesce(t.current_effective_medal, '')) "
        "  WHEN 'GOLD' THEN 4 WHEN 'SILVER' THEN 3 WHEN 'BRONZE' THEN 2 WHEN 'WOOD' THEN 1 ELSE 0 END DESC, "
        "(COALESCE(t.file_count, 0) > 0 OR COALESCE(t.evidence_count, 0) > 0) DESC, "
        "CASE upper(coalesce(t.crm_stage, '')) WHEN 'TORGI' THEN 0 ELSE 1 END ASC, "
        "COALESCE(t.end_date, DATE '1900-01-01') DESC, "
        "t.procurement_id, t.commercial_category_code LIMIT %s"
    )
    parameters.append(int(limit))
    try:
        raw_rows = crm_db.execute_query(sql, tuple(parameters)) or []
    except Exception as exc:  # defensive: never break the page on schema drift
        return {"columns": list(layout_for(selected_mode)), "rows": [], "selected_mode": selected_mode, "error": str(exc)}
    result = build_workspace_rows(raw_rows, selected_mode=selected_mode, now=now)
    _merge_manual_categories(crm_db, result)
    _attach_queue_status(result["rows"])
    # "Только актуальные": drop finished rows. Direct supply also dies at the 80%
    # mark (WOOD cap); object/project keep living while the delivery window runs,
    # so only fully expired rows are removed for them.
    if only_active:
        from src.services.commercial_routing_v3.submission_window_temporal import (
            EXPIRED as _EXPIRED,
            TEMPORAL_UNKNOWN as _UNKNOWN,
            WOOD_CAP as _WOOD_CAP,
        )
        kept = []
        for row in result["rows"]:
            temporal = row.get("temporal") or {}
            bucket = temporal.get("temporal_bucket")
            if bucket == _EXPIRED:
                continue
            # Direct supply dies at the 80% mark only on its own torgi window;
            # a live delivery window keeps the row.
            if (bucket == _WOOD_CAP and selected_mode == DIRECT_SUPPLY
                    and temporal.get("window_basis") != "DELIVERY"):
                continue
            # No window at all -> not actionable, hide from the active view.
            if bucket == _UNKNOWN and not temporal.get("submission_deadline_at"):
                continue
            # No price (НМЦК missing) -> not actionable now, hide from the active view.
            if row.get("price_text") in (None, "", "—"):
                continue
            kept.append(row)
        result["rows"] = kept
    result["error"] = None
    return result


def _merge_manual_categories(crm_db: Any, result: Dict[str, Any]) -> None:
    """Добавить ручные категории (MANUAL) в те же строки read-model.

    Контракт: запись живёт в crm_manual_category_overrides; строка наследует
    procurement-поля закупки, но категория/медаль — свои (UNSCORED, без
    наследования). Авто-анализ эти записи не трогает.
    """
    rows = result.get("rows") or []
    if not rows or crm_db is None:
        return
    try:
        from src.services.manual_category_service import list_manual_categories
    except Exception:  # noqa: BLE001
        return
    base_by_pid = {}
    for r in rows:
        pid = r.get("procurement_id")
        if pid is not None and pid not in base_by_pid:
            base_by_pid[pid] = r
    extra = []
    for pid, base in base_by_pid.items():
        for m in list_manual_categories(crm_db, pid):
            row = dict(base)
            row["category_code"] = m.get("category_code")
            row["product_primary"] = m.get("category_name") or m.get("category_code")
            row["product_secondary"] = "Вручную"
            row["subcategory_code"] = m.get("subcategory_code")
            # Медаль: пользовательская, если задана; иначе честный UNSCORED.
            row["medal_current"] = str(m.get("manual_candidate_level") or "UNSCORED")
            row["medal_initial"] = None
            row["manual"] = True
            row["manual_by"] = m.get("reviewed_by")
            row["manual_at"] = str(m.get("reviewed_at") or "")
            row["manual_reason"] = m.get("manual_reason")
            extra.append(row)
    if extra:
        result["rows"] = rows + extra


_QUEUE_LABELS = {
    "PRE_RESEARCH_WAITING": "В очереди", "PENDING": "В очереди", "RETRY": "В очереди",
    "RUNNING": "Обработка", "PROCESSING": "Обработка",
    "COMPLETED": "Обработана", "NO_LINKS": "Нет документов",
    "CANCELLED": "Снята (≥80%)", "FAILED": "Ошибка",
}


def _attach_queue_status(rows: List[Dict[str, Any]]) -> None:
    """Статус документной очереди + позиция, оценка времени и «успеет ли».

    Оценка считается один раз на рендер (не на строку): средняя длительность
    последних COMPLETED задач × позиция / число воркеров. Если истории нет —
    позиция выводится, ETA не выдумывается.
    """
    ids = [r["procurement_id"] for r in rows if r.get("procurement_id")]
    if not ids:
        return
    try:
        import os
        import psycopg2
        from src.services.crm_db_runtime import require_crm_db_connect_kwargs
        kw = dict(require_crm_db_connect_kwargs())
        kw["dbname"] = os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence")
        kw["connect_timeout"] = 5
        conn = psycopg2.connect(**kw)
        depth = 0
        avg_sec = None
        workers = 1
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT DISTINCT ON (procurement_id) procurement_id, status, priority_score
                         FROM document_processing_queue
                        WHERE procurement_id = ANY(%s)
                        ORDER BY procurement_id, id DESC""",
                    (ids,),
                )
                latest = {int(pid): (st, pr) for pid, st, pr in cur.fetchall()}
                cur.execute("""SELECT COUNT(*) FROM document_processing_queue
                                WHERE status IN ('PENDING','PRE_RESEARCH_WAITING')""")
                depth = int((cur.fetchone() or [0])[0] or 0)
                cur.execute("""SELECT AVG(EXTRACT(EPOCH FROM (completed_at - started_at)))
                                 FROM (SELECT completed_at, started_at
                                         FROM document_processing_queue
                                        WHERE status='COMPLETED' AND completed_at IS NOT NULL
                                          AND started_at IS NOT NULL
                                          AND completed_at > started_at
                                        ORDER BY completed_at DESC LIMIT 300) t""")
                row_avg = cur.fetchone()
                avg_sec = float(row_avg[0]) if row_avg and row_avg[0] is not None else None
                cur.execute("""SELECT COUNT(*) FROM document_processing_queue
                                WHERE status='PROCESSING'""")
                active = int((cur.fetchone() or [0])[0] or 0)
                workers = max(1, min(11, active or 1))
                # Реальные счётчики из document_intelligence (CRM file_count бывает 0).
                doc_counts: Dict[int, int] = {}
                find_counts: Dict[int, int] = {}
                cur.execute("""SELECT procurement_id, COUNT(*) FROM document_files
                                WHERE procurement_id = ANY(%s) GROUP BY procurement_id""", (ids,))
                for pid, n in cur.fetchall():
                    doc_counts[int(pid)] = int(n or 0)
                cur.execute("""SELECT m.procurement_id, COUNT(*)
                                 FROM document_match_details d
                                 JOIN document_matches m ON m.id = d.match_id
                                WHERE m.procurement_id = ANY(%s) GROUP BY m.procurement_id""", (ids,))
                for pid, n in cur.fetchall():
                    find_counts[int(pid)] = int(n or 0)
                positions = {}
                for pid, (status, prio) in latest.items():
                    if str(status).upper() in ("PENDING", "PRE_RESEARCH_WAITING"):
                        cur.execute("""SELECT COUNT(*) FROM document_processing_queue
                                        WHERE status IN ('PENDING','PRE_RESEARCH_WAITING')
                                          AND (COALESCE(priority_score,0) > COALESCE(%s,0)
                                               OR (COALESCE(priority_score,0) = COALESCE(%s,0)
                                                   AND procurement_id < %s))""",
                                    (prio, prio, pid))
                        positions[pid] = int((cur.fetchone() or [0])[0] or 0) + 1
        finally:
            conn.close()
    except Exception:
        return
    for row in rows:
        pid = int(row["procurement_id"]) if row.get("procurement_id") else -1
        entry = latest.get(pid)
        if not entry:
            continue
        status, _prio = entry
        label = _QUEUE_LABELS.get(str(status).upper(), str(status))
        pos = positions.get(pid)
        if pos:
            label += f" · {pos}-й из {depth}"
            if avg_sec:
                eta = avg_sec * pos / workers
                label += f" · ~{format_seconds(eta)}"
                rem = (row.get("temporal") or {}).get("remaining_seconds")
                if rem is not None:
                    row["queue_fits"] = bool(eta <= float(rem))
        row["queue_text"] = label
        row["queue_position"] = pos
        row["queue_depth"] = depth
        docs_n = doc_counts.get(pid)
        finds_n = find_counts.get(pid)
        if str(status).upper() == "COMPLETED":
            extra = []
            if docs_n is not None:
                extra.append(f"{docs_n} док")
            if finds_n is not None:
                extra.append(f"{finds_n} находок")
            if extra:
                row["queue_text"] = label + " · " + " · ".join(extra)
        # «Документы»: если CRM-счётчик пуст, показываем реальное число из DI.
        if docs_n and str(row.get("documents_text") or "—").strip() in ("—", "-", ""):
            row["documents_text"] = f"{docs_n} ✓"
        if finds_n is not None:
            row["findings_count"] = finds_n


def load_filter_options(crm_db: Any) -> Dict[str, Any]:
    """Read-only navigation options: categories, subcategories, objects, regions."""
    empty = {"categories": [], "subcategories": [], "objects": [], "regions": []}
    if crm_db is None:
        return empty
    try:
        categories = crm_db.execute_query("""
            SELECT o.commercial_category_code AS code,
                   COALESCE(c.category_name, o.commercial_category_code) AS name,
                   count(*) AS n,
                   COALESCE(sum(p.initial_price), 0) AS amount,
                   COALESCE(sum(p.initial_price) FILTER (WHERE o.opportunity_track = 'DIRECT_SUPPLY'), 0) AS direct_amount
            FROM crm_procurement_category_opportunities o
            JOIN crm_procurements p ON p.id = o.procurement_id
            LEFT JOIN crm_product_categories c ON c.category_code = o.commercial_category_code
            WHERE o.status = 'CURRENT'
            GROUP BY 1, 2
        """) or []
        subcategories = crm_db.execute_query("""
            SELECT o.commercial_category_code AS category_code,
                   o.commercial_subcategory_code AS code,
                   COALESCE(s.subcategory_name, o.commercial_subcategory_code) AS name,
                   count(*) AS n,
                   COALESCE(sum(p.initial_price), 0) AS amount
            FROM crm_procurement_category_opportunities o
            JOIN crm_procurements p ON p.id = o.procurement_id
            LEFT JOIN crm_product_subcategories s
              ON s.subcategory_code = o.commercial_subcategory_code
             AND s.category_id = (SELECT c.id FROM crm_product_categories c
                                  WHERE c.category_code = o.commercial_category_code ORDER BY c.id LIMIT 1)
            WHERE o.status = 'CURRENT' AND o.commercial_subcategory_code IS NOT NULL
            GROUP BY 1, 2, 3
        """) or []
        objects = crm_db.execute_query("""
            SELECT oc.object_type AS name, count(DISTINCT o.procurement_id) AS n
            FROM crm_procurement_category_opportunities o
            JOIN crm_procurement_object_classifications oc
              ON oc.procurement_id = o.procurement_id AND oc.is_current
            WHERE o.status = 'CURRENT' AND oc.object_type IS NOT NULL
            GROUP BY 1 ORDER BY n DESC LIMIT 40
        """) or []
        regions = crm_db.execute_query("""
            SELECT p.delivery_region AS name, count(*) AS n
            FROM crm_procurement_category_opportunities o
            JOIN crm_procurements p ON p.id = o.procurement_id
            WHERE o.status = 'CURRENT' AND p.delivery_region IS NOT NULL AND p.delivery_region <> ''
            GROUP BY 1 ORDER BY n DESC LIMIT 60
        """) or []
    except Exception:
        return empty
    def _weighted(row: Dict[str, Any]) -> float:
        amount = float(row.get("amount") or 0.0)
        direct = float(row.get("direct_amount") or 0.0)
        return direct * MODE_WEIGHT[DIRECT_SUPPLY] + (amount - direct) * MODE_WEIGHT[EMBEDDED_MATERIAL]

    cats = [dict(r) for r in categories]
    for row in cats:
        row["weighted"] = _weighted(row)
    cats.sort(key=lambda r: (-r["weighted"], -r["n"], r["name"]))

    subs = [dict(r) for r in subcategories]
    subs.sort(key=lambda r: (-float(r["amount"] or 0), -r["n"], r["name"]))

    return {
        "categories": cats,
        "subcategories": subs,
        "objects": [dict(r) for r in objects],
        "regions": [dict(r) for r in regions],
    }
