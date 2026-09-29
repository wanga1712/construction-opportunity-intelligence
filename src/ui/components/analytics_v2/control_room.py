"""Главный экран — control room (тёмная операторская панель).

Все значения приходят из ``main_dashboard_service.load_control_room``.
Виджет без данных показывает «—», а не 0; ошибка запроса отображается явно.

Доска рендерится ОДНИМ ``st.markdown``: весь экран — единый HTML-документ,
поэтому ``.cr-root`` оборачивает все секции и CSS-селекторы матчатся внутри
одного Streamlit-блока. Разбивать на несколько ``st.markdown`` нельзя —
иначе тёмная панель покрывает только свой блок.

Раскладка — три колонки (категории · возможности · состояние системы),
чтобы первая вьюпорта 1920x1080 содержала все шесть зон.
"""
from __future__ import annotations

from html import escape
from typing import List, Optional, Tuple

import streamlit as st

from src.services.main_dashboard_service import (
    AUTHORITY_LABELS,
    BUCKET_LABELS,
    ERROR_LABELS,
    FAMILY_LABELS,
    ControlRoom,
    format_age,
    load_control_room,
)

_STATUS_COLORS = {"GREEN": "#3fb950", "YELLOW": "#d29922", "RED": "#f85149", "UNKNOWN": "#6e7681"}
_MEDAL_COLORS = {"GOLD": "#e3b341", "SILVER": "#c9d1d9", "BRONZE": "#cd7f32", "WOOD": "#8b7355"}
_AUTH_SHORT = {
    "SECOND_PASS_MODEL": "2nd pass",
    "PRELIMINARY": "prelim",
    "EXPERT": "expert",
    "UNASSESSED": "—",
}
_TITLE_LIMIT = 70

_CSS = """<style>
.cr-root {
background: #0d1117;
border: 1px solid #1f2a37;
border-radius: 10px;
padding: 12px 14px 14px 14px;
margin-bottom: 14px;
font-family: "Segoe UI", -apple-system, Roboto, Helvetica, Arial, sans-serif;
color: #e6edf3;
}
.cr-strip { display: flex; gap: 8px; flex-wrap: wrap; }
.cr-ind {
flex: 1 1 170px; background: #131a24; border: 1px solid #1f2a37;
border-left-width: 3px; border-radius: 6px; padding: 6px 9px;
}
.cr-ind-label { font-size: 11px; letter-spacing: .04em; text-transform: uppercase; color: #8b98a5; }
.cr-ind-age { font-size: 15px; font-weight: 700; color: #e6edf3; margin-top: 1px; }
.cr-ind-cap { font-size: 10px; color: #6e7681; margin-top: 1px; }
.cr-sec { font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
color: #8b98a5; margin: 10px 0 5px 0; }
.cr-hero { display: flex; align-items: flex-end; gap: 20px; flex-wrap: wrap; }
.cr-hero-num { font-size: 40px; font-weight: 800; line-height: 1; color: #e6edf3; }
.cr-hero-cap { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: #8b98a5; }
.cr-sub { display: flex; gap: 16px; flex-wrap: wrap; }
.cr-sub-val { font-size: 18px; font-weight: 700; color: #e6edf3; }
.cr-sub-cap { font-size: 10px; color: #8b98a5; }
.cr-pipe { display: flex; align-items: stretch; gap: 5px; flex-wrap: wrap; }
.cr-stage { flex: 1 1 120px; background: #131a24; border: 1px solid #1f2a37;
border-radius: 6px; padding: 6px 5px; text-align: center; }
.cr-stage-val { font-size: 22px; font-weight: 800; color: #e6edf3; line-height: 1.1; }
.cr-stage-cap { font-size: 9px; letter-spacing: .05em; text-transform: uppercase; color: #8b98a5; margin-top: 2px; }
.cr-arrow { align-self: center; color: #30475e; font-size: 16px; }
.cr-gaps { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 6px; font-size: 11px; color: #8b98a5; }
.cr-gap b { color: #d29922; }
.cr-gap.err b { color: #f85149; }
.cr-grid3 { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr) minmax(0, 0.92fr);
gap: 16px; align-items: start; }
.cr-scroll { overflow-x: auto; }
.cr-tools { margin-bottom: 4px; }
.cr-tools-cap { font-size: 10px; color: #6e7681; line-height: 1.35; }
table.cr-t { width: 100%; border-collapse: collapse; font-size: 11px; }
table.cr-t th { text-align: right; padding: 3px 6px; color: #8b98a5; font-weight: 600;
border-bottom: 1px solid #1f2a37; white-space: nowrap; line-height: 1.25; }
table.cr-t th:first-child, table.cr-t td:first-child { text-align: left; }
table.cr-t td { padding: 2px 6px; border-bottom: 1px solid #161f2b; color: #c9d1d9; text-align: right;
vertical-align: top; line-height: 1.3; }
table.cr-t tr:hover td { background: #161f2b; }
table.cr-t a { color: #58a6ff; text-decoration: none; }
table.cr-t a:hover { text-decoration: underline; }
.cr-zero { color: #4a5568; }
.cr-num { white-space: nowrap; }
.cr-err { color: #f85149; font-weight: 600; }
.cr-note { font-size: 10px; color: #6e7681; margin-top: 2px; max-width: 215px;
overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cr-ok { color: #3fb950; }
@media (max-width: 1500px) { .cr-grid3 { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); } }
@media (max-width: 1050px) { .cr-grid3 { grid-template-columns: minmax(0, 1fr); } }
</style>"""


def _fmt(value: Optional[int]) -> str:
    if value is None:
        return '<span class="cr-err">\u2014</span>'
    return f"{value:,}".replace(",", "\u2009")


def _price(value: float | None) -> str:
    if value is None:
        return '<span class="cr-err">\u2014</span>'
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f} млрд"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} млн"
    if value >= 1_000:
        return f"{value / 1_000:.0f} тыс"
    return f"{value:.0f}"


def _cell(value: int, *, zero_soft: bool = True) -> str:
    if value == 0 and zero_soft:
        return '<span class="cr-zero">0</span>'
    return str(value)


def _short(value: str, limit: int = _TITLE_LIMIT) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "\u2026"


@st.cache_data(ttl=45, show_spinner=False)
def _load() -> ControlRoom:
    return load_control_room()


def _status_bar_html(room: ControlRoom) -> str:
    parts = ['<div class="cr-sec">ЧТО ПРОИСХОДИТ ПРЯМО СЕЙЧАС</div>', '<div class="cr-strip">']
    for ind in room.indicators:
        color = _STATUS_COLORS.get(ind.status, "#6e7681")
        age = "ошибка" if ind.error else format_age(ind.age_seconds)
        parts.append(
            f'<div class="cr-ind" style="border-left-color:{color}">'
            f'<div class="cr-ind-label">{escape(ind.label)}</div>'
            f'<div class="cr-ind-age" style="color:{color}">{escape(age)}</div>'
            f'<div class="cr-ind-cap">{escape(ind.caption)}</div>'
            f"</div>"
        )
    parts.append("</div>")
    return "".join(parts)


def _hero_html(room: ControlRoom) -> str:
    subs: List[Tuple[str, Optional[int]]] = [
        ("Новых за 24ч", room.new_24h),
        ("С документами", room.with_docs),
        ("Документы готовы", room.docs_complete),
        ("Second Pass готов", room.second_pass),
        ("MODEL authority", room.model_authority),
    ]
    sub_html = "".join(
        f'<div><div class="cr-sub-val">{_fmt(v)}</div>'
        f'<div class="cr-sub-cap">{escape(label)}</div></div>'
        for label, v in subs
    )
    return (
        '<div class="cr-sec">АКТИВНЫХ ТОРГОВ СЕЙЧАС</div>'
        '<div class="cr-hero">'
        f'<div><div class="cr-hero-num">{_fmt(room.active_total)}</div>'
        '<div class="cr-hero-cap">canonical actionable workset</div></div>'
        f'<div class="cr-sub">{sub_html}</div>'
        "</div>"
    )


def _pipeline_html(room: ControlRoom) -> str:
    parts = ['<div class="cr-sec">ГЛАВНЫЙ PIPELINE</div><div class="cr-pipe">']
    for idx, stage in enumerate(room.stages):
        if idx:
            parts.append('<div class="cr-arrow">&#9656;</div>')
        parts.append(
            f'<div class="cr-stage"><div class="cr-stage-val">{_fmt(stage.count)}</div>'
            f'<div class="cr-stage-cap">{escape(stage.label)}</div></div>'
        )
    parts.append("</div>")

    gaps = room.gaps or {}
    parts.append('<div class="cr-gaps">')
    for key, label, is_error in (
        ("no_links", "нет ссылок", False),
        ("waiting_docs", "ждут документов", False),
        ("no_evidence", "нет evidence", False),
        ("waiting_second_pass", "ждут Second Pass", False),
        ("download_errors", "ошибки загрузки", True),
    ):
        value = gaps.get(key)
        cls = "cr-gap err" if is_error else "cr-gap"
        parts.append(f'<div class="{cls}">{escape(label)}: <b>{_fmt(value)}</b></div>')
    parts.append("</div>")
    return "".join(parts)


def _categories_html(room: ControlRoom) -> str:
    parts = [
        '<div class="cr-sec">КАТЕГОРИИ · crm_product_categories</div>',
        '<div class="cr-tools"><span class="cr-tools-cap">'
        "Клик по названию → «Идут торги» с фильтром категории. Только активные "
        "canonical категории из crm_product_categories, COUNT(DISTINCT procurement_id). "
        "Док. — по документам, Ждут — ждут документов, Second Pass — run-linked результат v2."
        "</span></div>",
    ]
    head = (
        "<table class='cr-t'><thead><tr>"
        "<th>Категория</th><th>Активн.</th><th>Gold</th><th>Silver</th>"
        "<th>Bronze</th><th>Wood</th><th>Док.</th><th>Ждут</th>"
        "<th>Second Pass</th>"
        "</tr></thead><tbody>"
    )
    body = []
    for row in room.categories:
        link = f'<a href="?cr_cat={escape(row.code)}" target="_self">{escape(row.name)}</a>'
        body.append(
            f"<tr><td>{link}</td>"
            f"<td>{_cell(row.active)}</td>"
            f"<td>{_cell(row.gold)}</td>"
            f"<td>{_cell(row.silver)}</td>"
            f"<td>{_cell(row.bronze)}</td>"
            f"<td>{_cell(row.wood)}</td>"
            f"<td>{_cell(row.with_docs)}</td>"
            f"<td>{_cell(row.waiting_docs)}</td>"
            f"<td>{_cell(row.second_pass)}</td></tr>"
        )
    if not room.categories:
        body.append('<tr><td colspan="9" class="cr-err">Ошибка загрузки категорий</td></tr>')
    parts.append('<div class="cr-scroll">' + head + "".join(body) + "</tbody></table></div>")
    return "".join(parts)


def _opportunities_html(room: ControlRoom) -> str:
    parts = [
        '<div class="cr-sec">ТОП ВОЗМОЖНОСТЕЙ СЕЙЧАС</div>',
        '<div class="cr-tools"><span class="cr-tools-cap">'
        "Канонический CRM workset: EFFECTIVE_MEDAL → time decay → priority_score → "
        "срок → цена. Клик по номеру → «Идут торги»."
        "</span></div>",
    ]
    if not room.opportunities:
        parts.append('<div class="cr-err">Ошибка загрузки возможностей</div>')
        return "".join(parts)
    rows = []
    for item in room.opportunities:
        medal_color = _MEDAL_COLORS.get(item.effective_medal, "#6e7681")
        medal = item.category_medal if item.category_medal in _MEDAL_COLORS else None
        medal_html = (
            f'<span style="color:{_MEDAL_COLORS[medal]}">{escape(medal)}</span>'
            if medal else '<span class="cr-zero">\u2014</span>'
        )
        auth = escape(_AUTH_SHORT.get(item.base_authority, item.base_authority or "\u2014"))
        days = "\u2014" if item.days_left is None else f"{item.days_left:.0f} дн"
        link = (
            f'<a href="?cr_open={item.crm_id}" target="_self">'
            f"{escape(item.contract_number or str(item.crm_id))}</a>"
        )
        rows.append(
            f"<tr><td style='color:{medal_color};font-weight:700'>{escape(item.effective_medal)}"
            f"<div class='cr-note'>{auth}</div></td>"
            f"<td style='text-align:left'>{link}"
            f"<div class='cr-note'>{escape(_short(item.title))}</div></td>"
            f"<td style='text-align:left'>{escape(item.category)}"
            f"<div class='cr-note'>{medal_html}</div></td>"
            f"<td><span class='cr-num'>{_price(item.initial_price)}</span></td>"
            f"<td><span class='cr-num'>{escape(days)}</span></td></tr>"
        )
    header = (
        "<table class='cr-t'><thead><tr><th>Оценка</th>"
        "<th style='text-align:left'>Закупка</th>"
        "<th style='text-align:left'>Категория</th>"
        "<th>Цена</th><th>Осталось</th></tr></thead><tbody>"
    )
    parts.append('<div class="cr-scroll">' + header + "".join(rows) + "</tbody></table></div>")
    return "".join(parts)


def _authority_html(room: ControlRoom) -> str:
    parts = ['<div class="cr-sec">ИСТОЧНИК ТЕКУЩЕЙ ОЦЕНКИ</div>']
    parts.append('<div class="cr-sub" style="margin-bottom:8px">')
    for key, label in AUTHORITY_LABELS.items():
        value = room.authority.get(key, 0)
        cell = _cell(value) if room.authority else "\u2014"
        parts.append(
            f'<div><div class="cr-sub-val">{cell}</div>'
            f'<div class="cr-sub-cap">{escape(label)}</div></div>'
        )
    total = _fmt(room.authority_sum if room.authority else None)
    parts.append(
        f'<div><div class="cr-sub-val">{total}</div>'
        '<div class="cr-sub-cap">Σ = active workset</div></div>'
    )
    parts.append("</div>")

    if room.families:
        fam = " · ".join(
            f"{escape(FAMILY_LABELS.get(k, k))} <b>{v}</b>" for k, v in sorted(room.families.items())
        )
        parts.append(f'<div class="cr-gaps"><div class="cr-gap">Тип объекта: {fam}</div></div>')
    if room.deadlines:
        buckets = " · ".join(
            f"{escape(BUCKET_LABELS.get(k, k))} <b>{v}</b>" for k, v in room.deadlines.items()
        )
        parts.append(f'<div class="cr-gaps"><div class="cr-gap">Срок подачи: {buckets}</div></div>')
    if room.decay_affected is not None:
        parts.append(
            '<div class="cr-gaps"><div class="cr-gap">Понижено time decay: '
            f"<b>{room.decay_affected}</b></div></div>"
        )
    return "".join(parts)


def _doc_errors_html(room: ControlRoom) -> str:
    parts = ['<div class="cr-sec">ОШИБКИ ДОКУМЕНТОВ · 24Ч</div><div class="cr-gaps">']
    if room.doc_errors_total is None:
        parts.append('<div class="cr-gap err">Ошибка загрузки</div>')
    else:
        parts.append(
            f'<div class="cr-gap err">Нет ссылок: <b>{_fmt(room.gaps.get("no_links"))}</b> '
            "(не ошибка загрузки)</div>"
        )
        for key, count in room.doc_errors:
            label = ERROR_LABELS.get(key, key)
            cls = "cr-gap err" if key not in ("SKIPPED",) else "cr-gap"
            parts.append(f'<div class="{cls}">{escape(label)}: <b>{count}</b></div>')
    parts.append("</div>")
    return "".join(parts)


def _state_html(room: ControlRoom) -> str:
    return (
        '<div class="cr-sec">СОСТОЯНИЕ СИСТЕМЫ</div>'
        + _authority_html(room)
        + _doc_errors_html(room)
    )


def _footer_html(room: ControlRoom) -> str:
    bits = [f"собрано за {room.load_seconds:.1f} с"]
    if room.errors:
        bits.append('<span class="cr-err">ошибки: ' + escape("; ".join(room.errors)) + "</span>")
    else:
        bits.append('<span class="cr-ok">все источники доступны</span>')
    return f'<div class="cr-note" style="max-width:none">{" · ".join(bits)}</div>'


def render_control_room() -> None:
    """Полный главный экран. Никогда не бросает исключение."""
    try:
        room = _load()
    except Exception as exc:  # noqa: BLE001
        st.markdown(
            _CSS + '<div class="cr-root">'
            f'<div class="cr-err">Ошибка загрузки данных: {escape(str(exc))}</div></div>',
            unsafe_allow_html=True,
        )
        return

    grid = (
        '<div class="cr-grid3">'
        f"<div>{_categories_html(room)}</div>"
        f"<div>{_opportunities_html(room)}</div>"
        f"<div>{_state_html(room)}</div>"
        "</div>"
    )
    body = (
        '<div class="cr-root">'
        + _status_bar_html(room)
        + _hero_html(room)
        + _pipeline_html(room)
        + grid
        + _footer_html(room)
        + "</div>"
    )
    st.markdown(_CSS + body, unsafe_allow_html=True)