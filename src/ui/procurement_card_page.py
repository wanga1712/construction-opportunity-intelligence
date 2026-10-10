"""Карточка закупки CRM V2 — редизайн представления (WIP «Редизайн карточки CRM V2»).

Только представление: данные берутся из read-only
``procurement_card_dossier_service``, контракты/идентификаторы не меняются.
Структура: заголовок → 6 KPI-плиток → вкладки (Обзор / Документы / Находки /
Что можно поставить / Очередь). Модальное окно открывается из «Таблицы закупок».
"""
from __future__ import annotations

from html import escape
from typing import Any, Dict, List, Optional

import streamlit as st

from src.services.analytics_table_workspace_service import bucket_color, bucket_label
from src.services.commercial_routing_v3.submission_window_temporal import (
    EXPIRED,
    TEMPORAL_UNKNOWN,
    compute_submission_window,
    format_seconds,
)
from src.services.procurement_card_dossier_service import (
    list_procurements_for_card,
    load_procurement_dossier,
    queue_procurement_for_documents,
)

_MEDAL_CSS = {
    "GOLD": "#b8860b", "SILVER": "#6b7a8c", "BRONZE": "#a2601f", "WOOD": "#7a5c40",
}

# Человекочитаемые названия (отображение; данные в БД не меняются).
_CATEGORY_RU = {
    "lighting": "Светотехника", "waterproofing": "Гидроизоляция",
    "waterproofing_concrete_repair": "Гидроизоляция и ремонт бетона",
    "composite_structures": "Композитные конструкции", "composites": "Композиты",
    "flooring": "Напольные покрытия", "drainage_water_management": "Водоотвод и дренаж",
    "computers": "Вычислительная техника и ИТ", "cable_products": "Кабельная продукция",
    "cable_support_systems": "Кабеленесущие системы", "concrete_materials": "Материалы для бетона",
    "curbstone": "Бордюрный и бортовой камень",
    "external_utility_networks": "Наружные инженерные сети",
    "structural_reinforcement": "Усиление и ремонт конструкций",
    "bridge_road_infrastructure": "Мостовая и дорожная инфраструктура",
}
_TRACK_RU = {
    "EMBEDDED_MATERIAL": "В составе работ", "DIRECT_SUPPLY": "Прямая поставка",
    "DESIGN_REQUIREMENT": "Проект / влияние", "DESIGN_INFLUENCE": "Проект / влияние",
    "NO_COMMERCIAL_ENTRY": "Не наш профиль", "UNKNOWN": "Не определено",
}
_STATUS_RU = {
    "CURRENT": "Актуально", "SUPERSEDED": "Заменено новой версией",
    "PROCESSING": "В обработке", "ERROR": "Ошибка", "UNSCORED": "Без оценки",
}
_ACTION_RU = {
    "LIGHT_RESEARCH": "Краткая проверка", "PRIORITY_DOCS": "Приоритетные документы",
    "DOCUMENT_RESEARCH": "Исследование документов", "SKIP": "Пропустить",
    "METADATA_ONLY": "Только метаданные", "DISCOVER_COMMERCIAL_CATEGORY": "Поиск категории",
}


def _ru(mapping: Dict[str, str], value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "—"
    return mapping.get(raw) or mapping.get(raw.upper()) or escape(raw)

_CSS = """
<style>
:root{
  --pc-ink:#1b2430; --pc-muted:#7c8797; --pc-line:#e3e8ef; --pc-accent:#2066b0;
  --pc-bg:#ffffff; --pc-soft:#f6f8fb;
}
.pc-wrap-root{background:var(--pc-bg);color:var(--pc-ink);
  font-variant-numeric:tabular-nums}
.pc-head{border:1px solid var(--pc-line);border-radius:12px;padding:16px 18px;background:var(--pc-soft)}
.pc-row{display:flex;gap:14px;align-items:flex-start}
.pc-doc{font-size:28px;line-height:1}
.pc-main{flex:1 1 auto;min-width:0}
.pc-sub{font-size:11px;color:var(--pc-muted);font-weight:700;letter-spacing:.03em}
.pc-name{font-size:19px;font-weight:650;color:var(--pc-ink);line-height:1.35;
  margin-top:3px;word-break:break-word;overflow-wrap:anywhere}
.pc-link{font-size:12px;font-weight:600;color:var(--pc-accent);text-decoration:none}
.pc-info{flex:0 0 auto;margin-left:auto;text-align:right;font-size:11.5px;color:#41505f;
  min-width:200px;max-width:300px;line-height:1.5}
.pc-info div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pc-info .pc-info-strong{font-weight:700;color:var(--pc-ink);font-size:12.5px}
.pc-bar{position:relative;height:10px;border-radius:3px;background:#e6e9ee;overflow:hidden;margin:10px 0 3px}
.pc-fill{height:100%}
.pc-mark{position:absolute;top:-2px;width:2px;height:14px;background:#39424e;opacity:.55}
.pc-pct{font-size:11.5px;color:#39424e;font-weight:600}
.pc-tiles{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin:12px 0 4px}
.pc-tile{border:1px solid var(--pc-line);border-radius:12px;padding:10px 12px;background:#fff;min-width:0}
.pc-tile .cap{font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--pc-muted)}
.pc-tile b{font-size:18px;color:var(--pc-ink);display:block;line-height:1.25;margin-top:3px;
  word-break:break-word}
.pc-tile span.sub{font-size:11px;color:var(--pc-muted);display:block;margin-top:2px}
.pc-tile.warn b{color:#9c2c22}
.pc-card{border:1px solid var(--pc-line);border-radius:12px;padding:14px 16px;background:#fff}
.pc-sect{font-size:16px;font-weight:700;color:var(--pc-ink);margin:0 0 8px}
.pc-kv{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;font-size:12.5px}
.pc-kv dt{color:var(--pc-muted);white-space:nowrap}
.pc-kv dd{margin:0;color:var(--pc-ink);word-break:break-word;overflow-wrap:anywhere}
.pc-table{width:100%;border-collapse:separate;border-spacing:0;font-size:12.5px}
.pc-table thead th{background:var(--pc-soft);color:#455163;text-align:left;padding:6px 8px;
  border-bottom:1px solid var(--pc-line);white-space:nowrap;position:sticky;top:0}
.pc-table tbody td{padding:6px 8px;border-bottom:1px solid #eef1f5;vertical-align:top;
  word-break:break-word}
.pc-table tbody tr:hover{background:#f2f7ff}
.pc-muted{color:var(--pc-muted);font-size:12.5px}
.pc-mono{font-family:ui-monospace,Consolas,monospace;font-size:11.5px}
.pc-scroll{max-height:44vh;overflow:auto;border:1px solid var(--pc-line);border-radius:10px}
.pc-chip{display:inline-block;border:1px solid var(--pc-line);border-radius:11px;padding:1px 8px;
  font-size:11px;color:#41505f;background:#fff;margin:2px 4px 0 0}
.pc-chip.ok{background:#e9f6ec;border-color:#a9d3b2;color:#226b31}
.pc-chip.bad{background:#fdecea;border-color:#e0a09a;color:#9c2c22}
.pc-chip.warn{background:#fff4e5;border-color:#e6b273;color:#8a5a12}
.pc-flag{display:inline-block;border-radius:11px;padding:1px 9px;font-size:11px;font-weight:600;
  background:#fdecea;border:1px solid #e0a09a;color:#9c2c22}
.pc-badge{display:inline-block;border-radius:14px;padding:3px 12px;font-size:12.5px;font-weight:700;
  background:#eaf1fb;border:1px solid #b9cdea;color:#1c4f8a;margin-top:6px}
.pc-badge.warn{background:#fff4e5;border-color:#e6b273;color:#8a5a12}
.pc-inn{white-space:nowrap}
.pc-note{font-size:11px;color:#8a93a0;margin-top:2px}
@media (max-width:1200px){ .pc-tiles{grid-template-columns:repeat(3,minmax(0,1fr))} }
@media (max-width:900px){
  .pc-tiles{grid-template-columns:repeat(2,minmax(0,1fr))}
  .pc-row{flex-direction:column}
  .pc-info{text-align:left;margin-left:0;max-width:none}
}
</style>
"""


def _fmt(v: Any) -> str:
    if v is None or v == "":
        return "—"
    return escape(str(v))


def _date(v: Any) -> str:
    """Единый формат даты dd.mm.yyyy; отсутствие → «Не определено»."""
    if v is None or v == "":
        return "Не определено"
    text = str(v)[:10]
    parts = text.split("-")
    if len(parts) == 3 and len(parts[0]) == 4:
        return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return escape(str(v))


def _money(v: Any) -> str:
    try:
        return f"{float(v):,.0f}".replace(",", " ") + " ₽"
    except (TypeError, ValueError):
        return "—"


def _prov_chip(status: Any) -> str:
    s = str(status or "UNKNOWN").upper()
    cls = {"VERIFIED": "ok", "INVALID": "bad", "LEGACY_UNVERIFIED": "warn"}.get(s, "")
    return f'<span class="pc-chip {cls}">{escape(s)}</span>'


def _medal_span(medal: Any) -> str:
    s = str(medal or "").upper()
    if not s:
        return "—"
    color = _MEDAL_CSS.get(s)
    return f'<b style="color:{color}">{escape(s)}</b>' if color else escape(s)


def _window_html(window: Dict[str, Any]) -> str:
    bucket = window.get("temporal_bucket") or TEMPORAL_UNKNOWN
    if bucket == TEMPORAL_UNKNOWN:
        return '<div class="pc-muted" style="margin-top:8px">Окно подачи: срок не определён</div>'
    color = bucket_color(bucket)
    if window.get("window_basis") == "DEADLINE_ONLY":
        return (
            f'<div class="pc-bar"><div class="pc-fill" style="width:100%;background:{color};'
            f'opacity:.45"></div></div><div class="pc-pct">{escape(bucket_label(bucket))} · '
            f'до окончания {format_seconds(window.get("seconds_to_deadline"))}</div>'
        )
    ratio = window.get("window_consumed_ratio")
    pct = 100 if bucket == EXPIRED else round(float(ratio or 0.0) * 100)
    markers = "".join(
        f'<span class="pc-mark" style="left:{int(p * 100)}%"></span>' for p in (0.40, 0.60, 0.80)
    )
    label = (
        '<span class="pc-flag">Приём завершён</span>'
        if bucket == EXPIRED else escape(bucket_label(bucket))
    )
    return (
        f'<div class="pc-bar"><div class="pc-fill" style="width:{pct}%;background:{color}"></div>'
        f'{markers}</div>'
        f'<div class="pc-pct">{label} · осталось '
        f'{format_seconds(window.get("remaining_seconds"))} · использовано {pct}%</div>'
    )


def _tile(cap: str, value: str, sub: str = "", warn: bool = False) -> str:
    cls = "pc-tile warn" if warn else "pc-tile"
    sub_html = f'<span class="sub">{sub}</span>' if sub else ""
    return f'<div class="{cls}"><div class="cap">{escape(cap)}</div><b>{value}</b>{sub_html}</div>'


def _display_status(ident: Dict[str, Any], md: Dict[str, Any],
                    window: Dict[str, Any]) -> tuple:
    """Единый пользовательский статус (read-model). Возвращает (текст, tone, пояснение)."""
    from datetime import date as _date

    today = _date.today()
    bucket = window.get("temporal_bucket") or TEMPORAL_UNKNOWN
    stage = str(ident.get("crm_stage") or "")
    award = str(ident.get("award_status") or "")
    exec_start = _as_date(md.get("execution_start_at")) or _as_date(md.get("delivery_start_date"))
    exec_end = _as_date(md.get("execution_end_at")) or _as_date(md.get("delivery_end_date"))
    awarded = stage in ("razygranye", "commission") or award in ("awarded", "submission_closed_waiting_award")

    if bucket not in (EXPIRED, TEMPORAL_UNKNOWN):
        return "Идут торги", "", "приём заявок открыт"
    if awarded:
        if exec_end and exec_end < today:
            return "Исполнено", "", f"плановое окончание {exec_end:%d.%m.%Y}"
        if exec_start and exec_start <= today:
            return "Идёт исполнение", "", "по плановым датам; факт исполнения источником не подтверждён"
        if exec_start:
            return "Ожидает исполнения", "warn", f"плановое начало {exec_start:%d.%m.%Y}"
        return "Победитель определён", "warn", "исполнение не подтверждено"
    if bucket == EXPIRED:
        return "Подведение итогов", "warn", "источник не подтвердил победителя"
    return "Статус уточняется", "warn", "недостаточно данных"


def _as_date(value: Any):
    from datetime import date as _date

    if value is None or value == "":
        return None
    text = str(value)[:10]
    try:
        y, m, d = text.split("-")
        return _date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


def _execution_html(md: Dict[str, Any]) -> str:
    """Шкала периода исполнения (для объектов с контрактом), а не торгов."""
    from datetime import date as _date

    start = _as_date(md.get("execution_start_at")) or _as_date(md.get("delivery_start_date"))
    end = _as_date(md.get("execution_end_at")) or _as_date(md.get("delivery_end_date"))
    if not start or not end or end < start:
        return ('<div class="pc-muted" style="margin-top:8px">'
                'Срок исполнения не определён</div>')
    today = _date.today()
    total = (end - start).days or 1
    elapsed = max(0, min(total, (today - start).days))
    pct = round(elapsed / total * 100)
    remaining = max(0, (end - today).days)
    color = "#2f7d4f" if pct < 60 else ("#c8891a" if pct < 90 else "#b4453a")
    return (
        f'<div class="pc-bar"><div class="pc-fill" style="width:{pct}%;background:{color}"></div>'
        f'<span class="pc-mark" style="left:40%"></span>'
        f'<span class="pc-mark" style="left:80%"></span></div>'
        f'<div class="pc-pct">Исполнение: {start:%d.%m.%Y} ━━━ {end:%d.%m.%Y} · '
        f'прошло {pct}% · осталось {remaining} дн.</div>'
        f'<div class="pc-note">По плановым датам (не фактическая готовность работ)</div>'
    )


def _kv(pairs: List[List[str]]) -> str:
    body = "".join(f"<dt>{escape(k)}</dt><dd>{v}</dd>" for k, v in pairs)
    return f'<dl class="pc-kv">{body}</dl>'


def _table_html(columns: List[str], rows: List[List[str]], wrap: bool = True) -> str:
    if not rows:
        return '<div class="pc-muted">Категорийные возможности не найдены</div>'
    head = "".join(f"<th>{escape(c)}</th>" for c in columns)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    table = f'<table class="pc-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
    return f'<div class="pc-scroll">{table}</div>' if wrap else table


def _render_history_tab(pid: int, db: Any) -> None:
    """Вкладка «История / Модель»: таймлайн закупки и точный model_input/промпт."""
    try:
        from src.services.crm_procurement_history_service import (
            load_history,
            load_model_prompt,
            timeline_lines,
        )
    except Exception as exc:  # noqa: BLE001
        st.caption(f"История недоступна: {type(exc).__name__}")
        return
    history = load_history(db, pid)
    lines = timeline_lines(history) or []
    if lines:
        for line in lines:
            st.markdown(f"- {line}")
    else:
        st.markdown('<div class="pc-muted">Событий по закупке не найдено.</div>',
                    unsafe_allow_html=True)
    payload = load_model_prompt(db, pid) or {}
    st.markdown("**В модель уходит (model_input)**")
    if isinstance(payload.get("model_input"), dict):
        st.json(payload["model_input"])
    else:
        st.caption(f"model_input недоступен: {payload.get('result')}")
    if payload.get("prompt"):
        st.text_area("Текст промпта", payload["prompt"], height=320, key=f"pc_prompt_{pid}")
    else:
        st.caption("Промпт не отрендерился (нет model_input).")


def _render_dossier(d: Dict[str, Any], db: Any = None) -> None:
    ident = d.get("identity") or {}
    md = d.get("money_and_dates") or {}
    parties = d.get("parties") or {}
    counts = d.get("counts") or {}
    opps = d.get("opportunities") or []
    pid = d.get("procurement_id")
    link = ident.get("tender_link")

    best_medal = next((o.get("current_effective_medal") for o in opps
                       if o.get("current_effective_medal")), None)
    window = compute_submission_window(
        submission_start_at=md.get("start_date"),
        submission_deadline_at=md.get("end_date"),
        baseline_medal=best_medal,
    )
    expired = (window.get("temporal_bucket") or TEMPORAL_UNKNOWN) == EXPIRED
    status_text, status_tone, status_note = _display_status(ident, md, window)
    contract_stage = str(ident.get("crm_stage") or "") in ("razygranye", "commission")
    timeline_html = (
        _execution_html(md) if contract_stage and (md.get("execution_start_at")
                                                   or md.get("delivery_start_date"))
        else _window_html(window)
    )

    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(
        f'<div class="pc-wrap-root">'
        f'<div class="pc-head"><div class="pc-row">'
        f'<div class="pc-doc">📄</div>'
        f'<div class="pc-main">'
        f'<div class="pc-sub">ID {pid} · № {_fmt(ident.get("contract_number"))}</div>'
        f'<div class="pc-name">{_fmt(ident.get("auction_name"))}</div>'
        + (f'<div style="margin-top:4px"><a class="pc-link" href="{escape(str(link))}" '
           f'target="_blank">открыть закупку на внешнем сайте ↗</a></div>' if link else "")
        + f'</div>'
        f'<div class="pc-info">'
        f'<div class="pc-info-strong">{_fmt(ident.get("law"))}</div>'
        f'<div>ОКПД {_fmt(ident.get("okpd_code"))} · {_fmt(ident.get("region"))}</div>'
        f'<div>ЭТП: {_fmt(ident.get("trading_platform"))}</div>'
        f'<div>заказчик: {_fmt(parties.get("customer"))}</div>'
        f'</div></div>'
        f'<div class="pc-badge {status_tone}">{escape(status_text)}</div>'
        f'<div class="pc-note">{escape(status_note)}</div>'
        f'{timeline_html}</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<div class="pc-tiles">'
        + _tile("НМЦК", _money(md.get("initial_price")))
        + _tile("Начало", _date(md.get("start_date")))
        + _tile("Приём заявок до", _date(md.get("end_date")),
                "Приём завершён" if expired else "", warn=expired)
        + _tile("Документы", f'{counts.get("documents", 0)} / {counts.get("downloaded", 0)}',
                "всего / скачано")
        + _tile("Находки", str(counts.get("verified", 0)), "подтверждённых (VERIFIED)")
        + _tile("Категорийные возможности", str(counts.get("opportunities", 0)))
        + '</div>',
        unsafe_allow_html=True,
    )

    try:
        from src.services.direct_document_extractor import load_direct_extraction
        _direct = load_direct_extraction(pid)
    except Exception:  # noqa: BLE001
        _direct = {}
    _spec = _direct.get("spec") or []
    _tech = _direct.get("tech") or []
    _req = _direct.get("requirements") or []
    _secs = _direct.get("sections") or {}
    # Для прямой поставки разбираем смету — вкладка keyword-находок не нужна.
    _is_direct_track = any(
        str(o.get("opportunity_track") or "").upper() == "DIRECT_SUPPLY"
        for o in (d.get("opportunities") or [])
    )
    _titles = ["Обзор", f"Документы ({counts.get('documents', 0)})"]
    if not _is_direct_track:
        _titles.append(f"Находки ({counts.get('findings', 0)})")
    _titles.append(f"Что можно поставить ({len(d.get('supply_candidates') or [])})")
    _direct_specs = []
    if _spec:
        _direct_specs.append(("spec", f"Смета ({len(_spec)})"))
    if _tech:
        _direct_specs.append(("tech", f"Техпараметры ({len(_tech)})"))
    if _req or any((_direct.get("sections") or {}).values()):
        _req_total = len(_req) + sum(len(v or []) for v in (_direct.get("sections") or {}).values())
        _direct_specs.append(("req", f"Требования ({_req_total})"))
    _titles += [t for _, t in _direct_specs]
    _titles += ["История / Модель", "Очередь"]
    _tabs = st.tabs(_titles)
    _idx = 0
    tab_overview = _tabs[_idx]; _idx += 1
    tab_docs = _tabs[_idx]; _idx += 1
    tab_find = None
    if not _is_direct_track:
        tab_find = _tabs[_idx]; _idx += 1
    tab_supply = _tabs[_idx]; _idx += 1
    tab_spec = tab_tech = tab_req = None
    for _key, _ in _direct_specs:
        if _key == "spec":
            tab_spec = _tabs[_idx]
        elif _key == "tech":
            tab_tech = _tabs[_idx]
        else:
            tab_req = _tabs[_idx]
        _idx += 1
    tab_history, tab_queue = _tabs[_idx], _tabs[_idx + 1]

    with tab_overview:
        c1, c2 = st.columns(2, gap="medium")
        with c1:
            st.markdown('<div class="pc-card"><div class="pc-sect">📋 Основное</div>'
                        + _kv([
                            ["ID / №", f'{pid} · {_fmt(ident.get("contract_number"))}'],
                            ["Закон", _fmt(ident.get("law"))],
                            ["Способ / ЭТП", _fmt(ident.get("trading_platform"))],
                            ["Статус источника", _fmt(ident.get("source_status"))],
                            ["ОКПД", _fmt(ident.get("okpd_code"))],
                            ["Регион", _fmt(ident.get("region"))],
                            ["Адрес поставки", _fmt(md.get("delivery_address"))],
                        ]) + "</div>", unsafe_allow_html=True)
        with c2:
            st.markdown('<div class="pc-card"><div class="pc-sect">💰 Деньги и сроки</div>'
                        + _kv([
                            ["НМЦК", f'<b>{_money(md.get("initial_price"))}</b>'],
                            ["Начало подачи", _date(md.get("start_date"))],
                            ["Окончание подачи", _date(md.get("end_date"))],
                            ["Начало исполнения", _date(md.get("execution_start_at")
                                                        or md.get("delivery_start_date"))],
                            ["Окончание исполнения", _date(md.get("execution_end_at")
                                                           or md.get("delivery_end_date"))],
                            ["Обеспечение", _money(md.get("guarantee_amount"))],
                            ["Гарантия", _fmt(md.get("warranty_size"))],
                        ]) + "</div>", unsafe_allow_html=True)
        c3, c4 = st.columns(2, gap="medium")
        with c3:
            st.markdown('<div class="pc-card"><div class="pc-sect">🏢 Стороны</div>' + _table_html(
                ["Роль", "Наименование", "ИНН"],
                [
                    ["Заказчик", _fmt(parties.get("customer")), "—"],
                    ["Подрядчик/поставщик", _fmt(parties.get("contractor")),
                     f'<span class="pc-inn">{_fmt(parties.get("contractor_inn"))}</span>'],
                    ["Победитель (генподрядчик)", _fmt(parties.get("winner")),
                     f'<span class="pc-inn">{_fmt(parties.get("winner_inn"))}</span>'],
                    ["Балансодержатель", _fmt(parties.get("balance_holder")), "—"],
                ], wrap=False) + "</div>", unsafe_allow_html=True)
        with c4:
            st.markdown('<div class="pc-card"><div class="pc-sect">🏷 Категории и медаль</div>'
                        + _table_html(
                            ["Категория", "Режим", "Статус", "Медаль", "Балл", "Действие"],
                            [
                                [_ru(_CATEGORY_RU, o.get("commercial_category_code")),
                                 _ru(_TRACK_RU, o.get("opportunity_track")),
                                 _ru(_STATUS_RU, o.get("status")),
                                 _medal_span(o.get("current_effective_medal")),
                                 f'{_fmt(o.get("commercial_priority_score"))}/100'
                                 f'<div class="pc-note">prelim '
                                 f'{_fmt(o.get("candidate_medal"))} · conf '
                                 f'{_fmt(o.get("category_confidence"))}</div>',
                                 _ru(_ACTION_RU, o.get("research_action"))]
                                for o in opps
                            ]) + "</div>", unsafe_allow_html=True)
        with st.expander("＋ Добавить категорию вручную"):
            try:
                from src.services.manual_category_service import (
                    add_manual_category, list_categories, list_subcategories,
                )
                _cats = list_categories(db)
                _cat_map = {c["category_code"]: c.get("category_name") or c["category_code"]
                            for c in _cats}
                with st.form(key=f"pc_addform_{pid}", clear_on_submit=True):
                    f1, f2, f3 = st.columns([2, 2, 2])
                    _cat = f1.selectbox("Категория", list(_cat_map),
                                        format_func=_cat_map.get, key=f"pc_ac_{pid}")
                    _subs = {s["subcategory_code"]: (s.get("subcategory_name") or s["subcategory_code"])
                             for s in list_subcategories(_cat, db)} if _cat else {}
                    _sub = f2.selectbox("Подкатегория", ["—"] + list(_subs),
                                        format_func=lambda x: "—" if x == "—" else _subs.get(x, x),
                                        key=f"pc_as_{pid}")
                    _mode = f3.selectbox(
                        "Режим", ["EMBEDDED_MATERIAL", "DIRECT_SUPPLY", "DESIGN_REQUIREMENT"],
                        format_func=lambda m: {"EMBEDDED_MATERIAL": "В составе работ",
                                               "DIRECT_SUPPLY": "Прямая поставка",
                                               "DESIGN_REQUIREMENT": "Проект / влияние"}.get(m, m),
                        key=f"pc_am_{pid}")
                    _cm = st.text_input("Комментарий", key=f"pc_cm_{pid}")
                    if st.form_submit_button("＋ Добавить категорию") and _cat:
                        _res = add_manual_category(
                            pid, _cat, subcategory_code=(None if _sub == "—" else _sub),
                            mode=_mode, comment=_cm or None)
                        st.success(f"{_res.get('action')} · {_res.get('category_code')}"
                                   + (f" · {_res.get('error')}" if _res.get("error") else ""))
                        st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.caption(f"Форма недоступна: {type(exc).__name__}")

    with tab_docs:
        st.markdown(f'<div class="pc-muted">Скачано {counts.get("downloaded", 0)} из '
                    f'{counts.get("documents", 0)} · можно скачать '
                    f'{counts.get("downloadable", 0)} · повторно уже скачанное не качается.</div>',
                    unsafe_allow_html=True)
        st.markdown(_table_html(
            ["ID", "Файл", "Статус", "Ссылка", "Скачано", "Ошибка"],
            [
                [str(doc.get("id")), escape(str(doc.get("file_name") or "")),
                 _fmt(doc.get("download_status")),
                 (f'<a class="pc-link" href="{escape(str(doc.get("url")))}" target="_blank">'
                  f'скачать ↗</a>' if doc.get("url") else '<span class="pc-muted">нет ссылки</span>'),
                 _date(doc.get("downloaded_at")), _fmt(doc.get("error_message"))]
                for doc in (d.get("documents") or [])
            ]), unsafe_allow_html=True)

    if tab_find is not None:
        with tab_find:
            finds = d.get("findings") or []
            mode = st.radio("Показывать", ["Все", "VERIFIED", "INVALID/LEGACY"], horizontal=True,
                            key=f"pc_find_mode_{pid}", label_visibility="collapsed")
            if mode == "VERIFIED":
                finds = [f for f in finds if f.get("provenance_status") == "VERIFIED"]
            elif mode == "INVALID/LEGACY":
                finds = [f for f in finds if f.get("provenance_status") != "VERIFIED"]
            _all_finds = d.get("findings") or []
            _v = sum(1 for f in _all_finds if f.get("provenance_status") == "VERIFIED")
            _l = sum(1 for f in _all_finds if f.get("provenance_status") == "LEGACY_UNVERIFIED")
            _i = sum(1 for f in _all_finds if f.get("provenance_status") == "INVALID")
            st.caption(f"показано {len(finds)} из {counts.get('findings', 0)} · "
                       f"VERIFIED {_v} · LEGACY {_l} · INVALID {_i} · "
                       f"в модель можно отправлять только VERIFIED")
            st.markdown(_table_html(
                ["Термин", "Метод", "Score", "Provenance", "Строка", "matched_text", "Файл"],
                [
                    [_fmt(f.get("matched_term")), _fmt(f.get("match_method")), _fmt(f.get("score")),
                     _prov_chip(f.get("provenance_status")),
                     f'{_fmt(f.get("page_or_sheet"))} / {_fmt(f.get("row_number"))}',
                     f'<span class="pc-mono">{escape(str(f.get("matched_text") or "")[:180])}</span>',
                     escape(str(f.get("file_name") or ""))]
                    for f in finds[:150]
                ]), unsafe_allow_html=True)

    with tab_supply:
        supply = d.get("supply_candidates") or []
        if supply:
            st.markdown(_table_html(
                ["Товар/материал", "Бренд", "Модель", "Кол-во", "Цена", "Сумма", "Отношение", "Trust"],
                [
                    [escape(str(s.get("product_name_normalized") or s.get("product_name_raw") or "")),
                     _fmt(s.get("brand_normalized")), _fmt(s.get("model_article_normalized")),
                     f'{_fmt(s.get("quantity_value"))} {_fmt(s.get("quantity_unit_raw"))}',
                     _money(s.get("unit_price_value")), _money(s.get("total_price_value")),
                     _fmt(s.get("product_relation")), _fmt(s.get("structured_fact_trust_state"))]
                    for s in supply
                ]), unsafe_allow_html=True)
        else:
            st.markdown('<div class="pc-muted">Извлечённых товаров нет: extraction ещё не '
                        'прогнан. Кандидаты — вкладка «Находки», фильтр VERIFIED.</div>',
                        unsafe_allow_html=True)

    with tab_history:
        _render_history_tab(pid, db)

    if tab_spec is not None:
        with tab_spec:
            _h = (_spec[0].get("header") or []) if _spec else []
            st.markdown(_table_html(
                [_fmt(x) for x in (_h or ["Данные"])],
                [[_fmt(c) for c in it.get("cells") or []]
                 + [""] * max(0, len(_h) - len(it.get("cells") or []))
                 for it in _spec[:200]], wrap=True), unsafe_allow_html=True)
            st.caption("Закупка состоит из этих позиций (как есть, из документов).")

    if tab_tech is not None:
        with tab_tech:
            _h = (_tech[0].get("header") or []) if _tech else []
            st.markdown(_table_html(
                [_fmt(x) for x in (_h or ["Данные"])],
                [[_fmt(c) for c in it.get("cells") or []] for it in _tech[:300]],
                wrap=True), unsafe_allow_html=True)

    if tab_req is not None:
        with tab_req:
            if _req:
                _h = _req[0].get("header") or []
                st.markdown("**Национальный режим (таблица)**")
                st.markdown(_table_html(
                    [_fmt(x) for x in (_h or ["Данные"])],
                    [[_fmt(c) for c in it.get("cells") or []] for it in _req[:200]],
                    wrap=True), unsafe_allow_html=True)
            _SEC_TITLES = {
                "participant": "Требования к участнику",
                "product": "Требования к товару и поставке",
                "participation": "Условия участия",
                "security": "Обеспечение",
                "national": "Национальный режим",
            }
            for _key, _title in _SEC_TITLES.items():
                _items = _secs.get(_key) or []
                if not _items:
                    continue
                with st.expander(f"{_title} ({len(_items)})"):
                    for _it in _items[:40]:
                        st.markdown(f"- {_fmt(_it.get('text'))} "
                                    f"<span class=\"pc-muted\">· {_fmt(_it.get('source_file'))}</span>",
                                    unsafe_allow_html=True)

    with tab_queue:
        msg = st.session_state.pop("pcard_msg", None)
        if msg:
            (st.success if msg.get("ok") else st.warning)(
                f"{msg.get('action')} · queue_id={msg.get('queue_id')} · "
                f"priority={msg.get('priority_score')} · {msg.get('error') or ''}")
        st.markdown('<div class="pc-muted">Поставить закупку на скачивание/парсинг. '
                    '«Суперприоритет» — следующей после текущей обработки, не прерывая её. '
                    'Уже скачанное повторно не качается.</div>', unsafe_allow_html=True)
        confirm = st.checkbox("Подтверждаю постановку в документную очередь",
                              key=f"pcard_confirm_{pid}")
        b1, b2 = st.columns(2)
        if b1.button("Поставить в очередь", disabled=not confirm, key=f"pcard_q_{pid}"):
            st.session_state["pcard_msg"] = queue_procurement_for_documents(db, pid)
            st.rerun()
        if b2.button("⚡ Суперприоритет (следующей)", disabled=not confirm, key=f"pcard_su_{pid}"):
            st.session_state["pcard_msg"] = queue_procurement_for_documents(db, pid, superuser=True)
            st.rerun()
    if d.get("errors"):
        st.caption("Ошибки секций: " + ", ".join(map(str, d["errors"])))


def render_procurement_card_page(service) -> None:
    """Отдельная страница (в меню не выведена); основное открытие — из таблицы."""
    crm_db = getattr(service, "crm_db", None) if service is not None else None
    if crm_db is None:
        from src.services.db_bootstrap import connect_databases
        _radar, _tender, crm_db, _warn = connect_databases()
    st.title("Карточка закупки")
    items = list_procurements_for_card(crm_db, limit=200)
    if not items:
        st.info("Ничего не найдено.")
        return
    options = [str(p["id"]) for p in items]
    labels = {str(p["id"]): f"#{p['id']} · {p.get('contract_number') or '—'} · "
                            f"{str(p.get('auction_name') or '')[:60]}" for p in items}
    picked = st.selectbox("Закупка", options, format_func=lambda x: labels.get(x, x),
                          key="pcard_pick")
    _render_dossier(load_procurement_dossier(crm_db, int(picked)), crm_db)
