"""Analytics V2 command center — dense dark operational dashboard.

The whole top of «Аналитический контур V2» renders from ONE cached snapshot
(``load_analytics_command_snapshot``).  Switching page and coming back costs
zero DB round-trips while the snapshot is fresh.

Visual contract
---------------
* dark, compact, telemetry-dense grid; ~4 KPI cards per row at most;
* every number is factual; a failed section renders «Нет данных», never 0;
* animation is pure CSS (pulse / travelling glow) and never triggers a rerun;
* no internal table/worker/service name in the primary panels.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import List, Optional, Sequence

import streamlit as st

from src.services.analytics_command_center import (
    AnalyticsCommandSnapshot,
    load_analytics_command_snapshot,
)

SNAPSHOT_TTL_SEC = 60
_NO_DATA = "Нет данных"

_MEDAL_COLORS = {
    "GOLD": "#f5c518",
    "SILVER": "#c7d0d9",
    "BRONZE": "#d08d4f",
    "WOOD": "#9a7b5a",
}
_MEDALS = ("GOLD", "SILVER", "BRONZE", "WOOD")
_STATUS_COLORS = {
    "OK": "#22c55e",
    "CURRENT": "#22c55e",
    "WARNING": "#f59e0b",
    "STALE": "#f59e0b",
    "DOWN": "#ef4444",
    "COLLECTOR_DOWN": "#ef4444",
    "UNKNOWN": "#64748b",
}

_CC_CSS = """
<style>
.cc-wrap {
    background: #070c16;
    border: 1px solid #1c2740;
    border-radius: 12px;
    padding: 12px 14px 6px 14px;
    margin-bottom: 10px;
    font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    color: #dbe4f0;
}
.cc-wrap * { box-sizing: border-box; }
.cc-live {
    display: flex; flex-wrap: wrap; gap: 6px 18px; align-items: center;
    padding: 6px 10px; margin-bottom: 10px;
    background: linear-gradient(90deg, #0d1830 0%, #0a1425 100%);
    border: 1px solid #1d2b47; border-radius: 9px;
}
.cc-live-title {
    font-size: 10px; letter-spacing: 0.16em; font-weight: 700; color: #58a6ff;
}
.cc-live-item { display: flex; align-items: center; gap: 6px; font-size: 11.5px; }
.cc-live-item .ts { color: #6b7d99; font-variant-numeric: tabular-nums; }
.cc-dot {
    width: 8px; height: 8px; border-radius: 50%; display: inline-block;
    animation: cc-pulse 2.4s ease-in-out infinite;
}
@keyframes cc-pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: .45; transform: scale(.82); }
}
.cc-grid { display: grid; gap: 10px; margin-bottom: 10px; }
.cc-cols-3 { grid-template-columns: 1.05fr 1.75fr 1.05fr; }
.cc-cols-24 { grid-template-columns: 1.9fr 1fr; }
.cc-cols-3b { grid-template-columns: 1.6fr 1.05fr 1.05fr; }
.cc-panel {
    background: #0c1424; border: 1px solid #1b2740; border-radius: 10px;
    padding: 9px 11px 10px 11px; min-width: 0;
}
.cc-panel-title {
    font-size: 10px; letter-spacing: 0.14em; font-weight: 700; color: #7d90ad;
    text-transform: uppercase; margin-bottom: 8px;
}
.cc-big { font-size: 40px; font-weight: 750; line-height: 1.02; color: #ffffff;
          font-variant-numeric: tabular-nums; }
.cc-big-sub { font-size: 11px; color: #6b7d99; margin-top: 4px; }
.cc-split { display: flex; gap: 18px; margin-top: 10px; }
.cc-split .k { font-size: 11px; color: #6b7d99; }
.cc-split .v { font-size: 19px; font-weight: 700; color: #cfe0f5;
               font-variant-numeric: tabular-nums; }
.cc-buckets { display: flex; gap: 14px; margin-top: 10px; padding-top: 8px;
              border-top: 1px dashed #1e2c48; }
.cc-buckets .k { font-size: 10px; color: #6b7d99; }
.cc-buckets .v { font-size: 15px; font-weight: 700; color: #a9bdd8;
                 font-variant-numeric: tabular-nums; }
.cc-flow { display: flex; align-items: stretch; gap: 4px; }
.cc-node {
    flex: 1 1 0; min-width: 0; background: #0f1b30; border: 1px solid #22324f;
    border-radius: 8px; padding: 7px 8px;
}
.cc-node-label { font-size: 9.5px; color: #7d90ad; letter-spacing: .05em;
                 text-transform: uppercase; white-space: nowrap; overflow: hidden;
                 text-overflow: ellipsis; }
.cc-node-val { font-size: 21px; font-weight: 720; color: #e8f1ff;
               font-variant-numeric: tabular-nums; margin-top: 2px; }
.cc-arrow {
    display: flex; align-items: center; font-size: 14px;
    color: #35507a; padding: 0 1px; position: relative;
}
.cc-arrow .glow {
    position: absolute; top: 50%; left: 0; width: 5px; height: 5px;
    margin-top: -2.5px; border-radius: 50%; background: #38bdf8;
    box-shadow: 0 0 6px 2px rgba(56,189,248,.65);
    animation: cc-travel 2.6s linear infinite;
}
@keyframes cc-travel {
    0% { left: 0; opacity: 0; }
    15% { opacity: 1; }
    85% { opacity: 1; }
    100% { left: 100%; opacity: 0; }
}
.cc-losses { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }
.cc-loss {
    font-size: 10.5px; padding: 3px 8px; border-radius: 6px;
    background: rgba(239,68,68,.10); border: 1px solid rgba(239,68,68,.35);
    color: #f3a3a3;
}
.cc-loss.warn { background: rgba(245,158,11,.10);
                border-color: rgba(245,158,11,.35); color: #f3c98b; }
.cc-loss.info { background: rgba(56,189,248,.10);
                border-color: rgba(56,189,248,.30); color: #9fd8f5; }
.cc-table { width: 100%; border-collapse: collapse; font-size: 11.5px; }
.cc-table th {
    text-align: right; font-size: 9.5px; letter-spacing: .07em; color: #7186a4;
    text-transform: uppercase; font-weight: 600; padding: 3px 6px;
    border-bottom: 1px solid #1d2b47; white-space: nowrap;
}
.cc-table th.l, .cc-table td.l { text-align: left; }
.cc-table td {
    padding: 3px 6px; text-align: right; color: #c2d2e6;
    font-variant-numeric: tabular-nums; border-bottom: 1px solid #131e33;
    white-space: nowrap;
}
.cc-table td.name { color: #e2ecf9; font-weight: 600; }
.cc-table tr:hover td { background: #12203a; }
.cc-matrix td.axis { color: #7186a4; font-size: 9.5px; text-transform: uppercase;
                     letter-spacing: .06em; text-align: left; }
.cc-cell { border-radius: 5px; padding: 4px 6px; text-align: center;
           font-weight: 650; color: #0b1220; }
.cc-cell.zero { background: #101c31; color: #3c4d68; }
.cc-bar { height: 7px; border-radius: 4px; background: #16233c; overflow: hidden; }
.cc-bar > i { display: block; height: 100%; background: linear-gradient(90deg,#38bdf8,#6366f1); }
.cc-prov { display: flex; flex-direction: column; gap: 7px; }
.cc-prov-row { font-size: 11px; }
.cc-prov-row .t { display: flex; justify-content: space-between; color: #b9c9de;
                  margin-bottom: 3px; }
.cc-prov-row .t b { color: #e8f1ff; font-variant-numeric: tabular-nums; }
.cc-health-row { display: flex; align-items: center; justify-content: space-between;
                 font-size: 11.5px; padding: 3px 0;
                 border-bottom: 1px solid #131e33; }
.cc-health-row .lbl { color: #c2d2e6; display: flex; align-items: center; gap: 7px; }
.cc-health-row .st { color: #7d90ad; font-size: 10.5px; }
.cc-empty { font-size: 11.5px; color: #f0a35e; }
.cc-legend { font-size: 10px; color: #6b7d99; margin-top: 7px; }
.cc-foot { font-size: 10px; color: #56698a; padding: 2px 2px 4px 2px; }
</style>
"""


# ── formatting helpers ────────────────────────────────────────────────────

def _fmt(value: Optional[int]) -> str:
    if value is None:
        return _NO_DATA
    return f"{int(value):,}".replace(",", " ")


def _metric(metric) -> str:
    if not getattr(metric, "ok", False):
        return _NO_DATA
    return _fmt(metric.value)


def _pct(part: int, whole: int) -> str:
    if not whole:
        return "—"
    return f"{100.0 * part / whole:.0f}%"


def _status_color(status: str) -> str:
    for key, color in _STATUS_COLORS.items():
        if status.upper().startswith(key):
            return color
    return "#64748b"


def _hhmm(value: Optional[datetime]) -> str:
    if not isinstance(value, datetime):
        return ""
    return value.strftime("%H:%M")


# ── snapshot access (single cached read model) ────────────────────────────

@st.cache_data(ttl=SNAPSHOT_TTL_SEC, show_spinner=False)
def _cached_snapshot() -> AnalyticsCommandSnapshot:
    return load_analytics_command_snapshot()


def invalidate_command_center_snapshot() -> None:
    """Targeted refresh: clears ONLY the command-center snapshot."""
    try:
        _cached_snapshot.clear()
    except Exception:
        pass


# ── panels ────────────────────────────────────────────────────────────────

def _render_live_bar(snap: AnalyticsCommandSnapshot) -> None:
    items: List[str] = []
    if snap.health_ok:
        for item in snap.health:
            color = _status_color(item.status)
            ts = f"<span class='ts'>{escape(item.timestamp)}</span>" if item.timestamp else ""
            items.append(
                "<div class='cc-live-item'>"
                f"<span class='cc-dot' style='background:{color}'></span>"
                f"<span>{escape(item.label)}</span>{ts}</div>"
            )
    else:
        items.append(
            "<div class='cc-live-item'>"
            "<span class='cc-dot' style='background:#ef4444'></span>"
            "<span>Снимок состояния недоступен</span></div>"
        )
    built = snap.built_at.astimezone().strftime("%H:%M:%S")
    items.append(
        f"<div class='cc-live-item'><span class='ts'>снимок данных: {built}</span></div>"
    )
    st.markdown(
        "<div class='cc-live'><span class='cc-live-title'>LIVE</span>"
        + "".join(items)
        + "</div>",
        unsafe_allow_html=True,
    )


def _render_active(snap: AnalyticsCommandSnapshot) -> None:
    buckets = snap.active_buckets or {}
    bucket_html = "".join(
        f"<div><div class='k'>{escape(str(k))}</div>"
        f"<div class='v'>{_fmt(v)}</div></div>"
        for k, v in buckets.items()
    )
    st.markdown(
        "<div class='cc-panel'>"
        "<div class='cc-panel-title'>Активные торги сейчас</div>"
        f"<div class='cc-big'>{_metric(snap.active_total)}</div>"
        "<div class='cc-big-sub'>закупки с открытым приёмом заявок</div>"
        "<div class='cc-split'>"
        f"<div><div class='k'>44-ФЗ</div><div class='v'>{_metric(snap.active_44)}</div></div>"
        f"<div><div class='k'>223-ФЗ</div><div class='v'>{_metric(snap.active_223)}</div></div>"
        "<div><div class='k'>Разыграно</div>"
        f"<div class='v'>{_metric(snap.awarded_44)} / {_metric(snap.awarded_223)}</div></div>"
        "</div>"
        f"<div class='cc-buckets'>{bucket_html}</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def _render_pipeline(snap: AnalyticsCommandSnapshot) -> None:
    nodes = snap.pipeline_nodes
    if not nodes:
        st.markdown(
            "<div class='cc-panel'><div class='cc-panel-title'>Конвейер</div>"
            f"<div class='cc-empty'>{_NO_DATA}</div></div>",
            unsafe_allow_html=True,
        )
        return

    parts: List[str] = []
    for index, node in enumerate(nodes):
        if index:
            parts.append("<div class='cc-arrow'><span class='glow'></span>&#9654;</div>")
        parts.append(
            "<div class='cc-node'>"
            f"<div class='cc-node-label'>{escape(node.label)}</div>"
            f"<div class='cc-node-val'>{_metric(node)}</div>"
            "</div>"
        )
    losses = "".join(
        f"<div class='cc-loss {'warn' if 'Ошибк' in l.label else 'info'}'>"
        f"{escape(l.label)}: <b>{_fmt(l.value) if l.ok else _NO_DATA}</b></div>"
        for l in snap.pipeline_losses
    )
    new_line = (
        "<div class='cc-legend'>"
        f"Загружено в CRM за 24 ч: {_metric(snap.new_24h_44)} · {_metric(snap.new_24h_223)}"
        f" &nbsp;|&nbsp; нового по дате начала: {_metric(snap.new_source_1d)} за 24 ч"
        " (не «новые закупки»)</div>"
    )
    st.markdown(
        "<div class='cc-panel'>"
        "<div class='cc-panel-title'>Конвейер обработки</div>"
        f"<div class='cc-flow'>{''.join(parts)}</div>"
        f"<div class='cc-losses'>{losses}</div>"
        f"{new_line}"
        "</div>",
        unsafe_allow_html=True,
    )


def _render_authority(snap: AnalyticsCommandSnapshot) -> None:
    prov = snap.provenance[:4]
    total = sum(v for _, v in prov) or 1
    rows = "".join(
        "<div class='cc-prov-row'>"
        f"<div class='t'><span>{escape(k)}</span><b>{_fmt(v)}</b></div>"
        f"<div class='cc-bar'><i style='width:{100.0 * v / total:.0f}%'></i></div>"
        "</div>"
        for k, v in prov
    ) if prov else f"<div class='cc-empty'>{_NO_DATA}</div>"
    st.markdown(
        "<div class='cc-panel'>"
        "<div class='cc-panel-title'>Кто поставил оценку</div>"
        f"<div class='cc-prov'>{rows}</div>"
        "<div class='cc-legend'>происхождение первичной медали</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def _render_category_matrix(snap: AnalyticsCommandSnapshot) -> None:
    rows = snap.categories
    if not snap.categories_ok or not rows:
        st.markdown(
            "<div class='cc-panel'><div class='cc-panel-title'>Матрица категорий</div>"
            f"<div class='cc-empty'>{_NO_DATA}</div></div>",
            unsafe_allow_html=True,
        )
        return
    head = "".join(
        f"<th style='color:{_MEDAL_COLORS[m]}'>{m}</th>" for m in _MEDALS
    )
    body: List[str] = []
    for row in rows:
        cells = "".join(
            f"<td>{row.medals.get(m, 0)}</td>" if row.medals.get(m) else "<td>·</td>"
            for m in _MEDALS
        )
        body.append(
            "<tr>"
            f"<td class='l name'>{escape(row.name)}</td>"
            f"<td>{row.opportunities}</td>"
            f"{cells}"
            f"<td>{row.actionable}</td>"
            "</tr>"
        )
    hidden = snap.categories_zero_hidden_names
    zero_note = ""
    if hidden:
        shown = ", ".join(hidden[:6])
        rest = f", ещё {len(hidden) - 6}" if len(hidden) > 6 else ""
        zero_note = (
            "<div class='cc-legend'>Без возможностей (не показано): "
            f"{escape(shown)}{rest}</div>"
        )
    st.markdown(
        "<div class='cc-panel'>"
        "<div class='cc-panel-title'>Категории · возможности</div>"
        "<table class='cc-table'><thead><tr>"
        "<th class='l'>Категория</th><th>Возм.</th>"
        f"{head}<th>Открыто</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
        "<div class='cc-legend'>Единица: закупка × товарная категория · "
        "медаль текущая эффективная</div>"
        f"{zero_note}"
        "</div>",
        unsafe_allow_html=True,
    )


def _render_health(snap: AnalyticsCommandSnapshot) -> None:
    if not snap.health_ok:
        st.markdown(
            "<div class='cc-panel'><div class='cc-panel-title'>Состояние серверов</div>"
            f"<div class='cc-empty'>{_NO_DATA}</div></div>",
            unsafe_allow_html=True,
        )
        return
    rows = "".join(
        "<div class='cc-health-row'>"
        f"<span class='lbl'><span class='cc-dot' style='background:"
        f"{_status_color(item.status)}'></span>{escape(item.label)}</span>"
        f"<span class='st'>{escape(item.timestamp or item.status)}</span>"
        "</div>"
        for item in snap.health
    )
    age = (
        f"обновлено {int(snap.health_age_sec)} с назад"
        if snap.health_age_sec is not None
        else ""
    )
    st.markdown(
        "<div class='cc-panel'>"
        "<div class='cc-panel-title'>Состояние серверов</div>"
        f"{rows}"
        f"<div class='cc-legend'>{escape(age)}</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def _render_top_opportunities(snap: AnalyticsCommandSnapshot) -> None:
    items = snap.top_opportunities
    if not snap.top_ok or not items:
        st.markdown(
            "<div class='cc-panel'><div class='cc-panel-title'>Топ возможностей</div>"
            f"<div class='cc-empty'>{_NO_DATA}</div></div>",
            unsafe_allow_html=True,
        )
        return
    body: List[str] = []
    for item in items:
        medal = item.medal if item.medal in _MEDAL_COLORS else ""
        badge = (
            f"<span style='color:{_MEDAL_COLORS[medal]};font-weight:700'>"
            f"{medal[:2]}</span>" if medal else "—"
        )
        label = f"{escape(item.value_text)}"
        if item.value_label:
            label += f"<div class='cc-foot'>{escape(item.value_label)}</div>"
        body.append(
            "<tr>"
            f"<td class='l'>{badge}</td>"
            f"<td class='l name'>№{escape(item.procurement_number)}"
            f"<div class='cc-foot'>{escape(item.procurement_name)}</div></td>"
            f"<td class='l'>{escape(item.category_name)}</td>"
            f"<td>{label}</td>"
            f"<td>{escape(item.deadline_text)}</td>"
            "</tr>"
        )
    st.markdown(
        "<div class='cc-panel'>"
        "<div class='cc-panel-title'>Топ-10 возможностей</div>"
        "<table class='cc-table'><thead><tr>"
        "<th class='l'></th><th class='l'>Закупка</th><th class='l'>Категория</th>"
        "<th>Сумма</th><th>Приём до</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
        "<div class='cc-legend'>Ранжирование: медаль → коммерческий приоритет. "
        "«НМЦК» — цена закупки, а не подтверждённая поставка</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def _render_medal_matrix(snap: AnalyticsCommandSnapshot) -> None:
    if not snap.medals_ok:
        st.markdown(
            "<div class='cc-panel'><div class='cc-panel-title'>Медали</div>"
            f"<div class='cc-empty'>{_NO_DATA}</div></div>",
            unsafe_allow_html=True,
        )
        return
    lookup = {(c.initial, c.final): c.count for c in snap.transition}
    rank = {"GOLD": 4, "SILVER": 3, "BRONZE": 2, "WOOD": 1}
    head = "".join(
        f"<th style='color:{_MEDAL_COLORS[m]}'>{m[:2]}</th>" for m in _MEDALS
    )
    body: List[str] = []
    for initial in _MEDALS:
        cells: List[str] = []
        for final in _MEDALS:
            count = lookup.get((initial, final), 0)
            if not count:
                cells.append("<td><div class='cc-cell zero'>·</div></td>")
                continue
            if rank[initial] == rank[final]:
                bg = "#3b5378"
            elif rank[final] < rank[initial]:
                bg = "#b0533f"
            else:
                bg = "#3f8f63"
            cells.append(
                f"<td><div class='cc-cell' style='background:{bg}'>{count}</div></td>"
            )
        body.append(
            f"<tr><td class='axis'>{initial}</td>" + "".join(cells) + "</tr>"
        )
    decided = (
        (snap.medal_same.value or 0)
        + (snap.medal_down.value or 0)
        + (snap.medal_up.value or 0)
    )
    st.markdown(
        "<div class='cc-panel'>"
        "<div class='cc-panel-title'>Медали: первичная → текущая</div>"
        "<table class='cc-table'><thead><tr><th class='l'>из \\ в</th>"
        f"{head}</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
        "<div class='cc-split'>"
        f"<div><div class='k'>Без изменений</div><div class='v'>{_measure(snap.medal_same, decided)}</div></div>"
        f"<div><div class='k'>Понижена</div><div class='v'>{_measure(snap.medal_down, decided)}</div></div>"
        f"<div><div class='k'>Повышена</div><div class='v'>{_measure(snap.medal_up, decided)}</div></div>"
        "</div></div>",
        unsafe_allow_html=True,
    )


def _measure(metric, whole: int) -> str:
    if not getattr(metric, "ok", False):
        return _NO_DATA
    return f"{_fmt(metric.value)} · {_pct(int(metric.value or 0), whole)}"


def _render_doc_errors(snap: AnalyticsCommandSnapshot) -> None:
    if not snap.doc_errors_ok:
        st.markdown(
            "<div class='cc-panel'><div class='cc-panel-title'>Документы · ошибки</div>"
            f"<div class='cc-empty'>{_NO_DATA}</div></div>",
            unsafe_allow_html=True,
        )
        return
    reasons = "".join(
        "<div class='cc-health-row'>"
        f"<span class='lbl'>{escape(reason[:58])}</span>"
        f"<span class='st'>{_fmt(count)}</span></div>"
        for reason, count in snap.doc_reasons
    ) or "<div class='cc-empty'>нет записанных причин</div>"
    st.markdown(
        "<div class='cc-panel'>"
        "<div class='cc-panel-title'>Документы · проблемы</div>"
        "<div class='cc-split'>"
        f"<div><div class='k'>Нет документов</div><div class='v'>{_metric(snap.doc_no_links)}</div></div>"
        f"<div><div class='k'>Ошибки</div><div class='v'>{_metric(snap.doc_failed)}</div></div>"
        "</div>"
        f"<div style='margin-top:8px'>{reasons}</div>"
        "</div>",
        unsafe_allow_html=True,
    )


# ── entry point ───────────────────────────────────────────────────────────

def render_command_center() -> None:
    """Render the whole top dashboard from one cached snapshot."""
    st.markdown(_CC_CSS, unsafe_allow_html=True)
    with st.spinner("Собираю сводку по данным…"):
        snap = _cached_snapshot()

    _render_live_bar(snap)

    if snap.errors:
        st.caption(
            "Часть разделов недоступна: " + ", ".join(sorted(set(snap.errors)))
        )

    st.markdown("<div class='cc-grid cc-cols-3'>", unsafe_allow_html=True)
    col_active, col_pipeline, col_authority = st.columns([1.05, 1.75, 1.05])
    with col_active:
        _render_active(snap)
    with col_pipeline:
        _render_pipeline(snap)
    with col_authority:
        _render_authority(snap)

    col_category, col_health = st.columns([1.9, 1.0])
    with col_category:
        _render_category_matrix(snap)
    with col_health:
        _render_health(snap)

    col_top, col_medals, col_errors = st.columns([1.6, 1.05, 1.05])
    with col_top:
        _render_top_opportunities(snap)
    with col_medals:
        _render_medal_matrix(snap)
    with col_errors:
        _render_doc_errors(snap)