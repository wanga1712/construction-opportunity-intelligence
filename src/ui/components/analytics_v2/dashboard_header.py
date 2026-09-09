"""Dashboard header — compact visual redesign with bounded width.

Presents procurement inventory, new arrivals, document pipeline process strip,
and commercial assessment quality in a tight, manager-friendly layout.
All data from analytics_dashboard_kpi_service.load_dashboard_kpi().

Visual invariants
-----------------
- Bounded container width: ~1200px max, centered horizontally.
- Compact KPI cards (180–250px width, 80–95px height).
- Process strip for document pipeline in a single container.
- 100% stacked medal bar chart removed from main screen.
- Detailed transition list and 4x4 matrix under collapsed expanders.
- Total dashboard header height ≈ 400–500px on desktop viewports.
"""

from __future__ import annotations

from html import escape
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from src.services.analytics_dashboard_kpi_service import (
    MEDAL_RANK,
    DashboardKPI,
    load_dashboard_kpi,
)

# ── Medal colors & emoji ──────────────────────────────────────────────────

_MEDAL_COLORS = {
    "GOLD": "#FFD700",
    "SILVER": "#C0C0C0",
    "BRONZE": "#CD7F32",
    "WOOD": "#8B7355",
}

_MEDAL_EMOJI = {
    "GOLD": "🥇",
    "SILVER": "🥈",
    "BRONZE": "🥉",
    "WOOD": "🪵",
}

# ── Compact CSS Layout ────────────────────────────────────────────────────

_COMPACT_DASHBOARD_CSS = """
<style>
.v2-dashboard-wrap {
    max-width: 1220px;
    margin: 0 auto;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
.v2-section-title {
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 0.04em;
    color: #1e293b;
    text-transform: uppercase;
    margin: 12px 0 4px 0;
}
.v2-section-caption {
    font-size: 12px;
    color: #64748b;
    margin: 0 0 8px 0;
}
.v2-kpi-grid-4 {
    display: grid;
    grid-template-columns: repeat(4, minmax(180px, 1fr));
    gap: 10px;
    margin-bottom: 6px;
}
.v2-kpi-grid-3 {
    display: grid;
    grid-template-columns: repeat(3, minmax(180px, 1fr));
    gap: 10px;
    margin-bottom: 8px;
}
.v2-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 10px 14px;
    min-height: 82px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: center;
}
.v2-card-label {
    font-size: 13px;
    font-weight: 500;
    color: #64748b;
    margin-bottom: 4px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.v2-card-val {
    font-size: 26px;
    font-weight: 700;
    color: #0f172a;
    line-height: 1.15;
}
.v2-card-pct {
    font-size: 14px;
    font-weight: 500;
    color: #64748b;
    margin-left: 6px;
}
.v2-secondary-line {
    font-size: 12px;
    color: #64748b;
    margin: 2px 0 12px 0;
    line-height: 1.4;
}
.v2-pipeline-strip {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 8px 6px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 4px;
}
.v2-pipeline-step {
    flex: 1;
    text-align: center;
    padding: 4px 6px;
}
.v2-pipeline-val {
    font-size: 22px;
    font-weight: 700;
    color: #0f172a;
    line-height: 1.15;
    margin-bottom: 3px;
}
.v2-pipeline-label {
    font-size: 12px;
    font-weight: 500;
    color: #64748b;
}
.v2-pipeline-sep {
    width: 1px;
    height: 32px;
    background: #e2e8f0;
    flex-shrink: 0;
}
@media (max-width: 900px) {
    .v2-kpi-grid-4 {
        grid-template-columns: repeat(2, 1fr);
    }
    .v2-kpi-grid-3 {
        grid-template-columns: 1fr;
    }
    .v2-pipeline-strip {
        flex-wrap: wrap;
    }
    .v2-pipeline-sep {
        display: none;
    }
    .v2-pipeline-step {
        flex-basis: 50%;
        margin-bottom: 8px;
    }
}
</style>
"""


# ── DB wrapper ────────────────────────────────────────────────────────────

class _CrmDBWrapper:
    """Minimal DB wrapper providing execute_query() for the KPI service."""

    def execute_query(self, sql: str, params: Any = None, **kw) -> list:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        from src.services.crm_db_runtime import require_crm_db_connect_kwargs

        conn = psycopg2.connect(**require_crm_db_connect_kwargs())
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params or ())
                return cur.fetchall()
        finally:
            conn.close()


# ── Formatting Helper ────────────────────────────────────────────────────

def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


# ── Main entry point ─────────────────────────────────────────────────────

def render_dashboard_header() -> None:
    """Render the full dashboard header — compact visual redesign."""
    crm_db = _CrmDBWrapper()

    def _doc_connect():
        import psycopg2
        from src.services.crm_db_runtime import require_crm_db_connect_kwargs
        kwargs = dict(require_crm_db_connect_kwargs())
        kwargs["dbname"] = "document_intelligence"
        kwargs["connect_timeout"] = 5
        return psycopg2.connect(**kwargs)

    kpi = load_dashboard_kpi(crm_db, doc_db_connect=_doc_connect)

    st.markdown(_COMPACT_DASHBOARD_CSS, unsafe_allow_html=True)

    # Wrap in centered bounded container
    st.markdown("<div class='v2-dashboard-wrap'>", unsafe_allow_html=True)
    _render_inventory(kpi)
    _render_pipeline_strip(kpi)
    _render_assessment(kpi)

    with st.expander("🔍 Диагностика", expanded=False):
        st.caption(
            f"Запросов: {kpi.query_count} · "
            f"Время: {kpi.query_time_ms:.0f} мс · "
            f"SOURCE_GAP: {', '.join(kpi.source_gaps) if kpi.source_gaps else '—'}"
        )
    st.markdown("</div>", unsafe_allow_html=True)


# ── Section 1: Procurement inventory + new arrivals ──────────────────────

def _render_inventory(kpi: DashboardKPI) -> None:
    """Procurement inventory cards and compact 24h arrivals note."""
    st.markdown("<div class='v2-section-title'>ЗАКУПКИ</div>", unsafe_allow_html=True)

    c44_t = _fmt(kpi.array.fz44_torgi)
    c223_t = _fmt(kpi.array.fz223_torgi)
    c44_r = _fmt(kpi.array.fz44_razygranye)
    c223_r = _fmt(kpi.array.fz223_razygranye) if kpi.array.fz223_razygranye > 0 else "—"

    cards_html = f"""
    <div class='v2-kpi-grid-4'>
        <div class='v2-card'>
            <div class='v2-card-label'>44-ФЗ · Торги</div>
            <div class='v2-card-val'>{c44_t}</div>
        </div>
        <div class='v2-card'>
            <div class='v2-card-label'>223-ФЗ · Торги</div>
            <div class='v2-card-val'>{c223_t}</div>
        </div>
        <div class='v2-card'>
            <div class='v2-card-label'>44-ФЗ · Разыгранные</div>
            <div class='v2-card-val'>{c44_r}</div>
        </div>
        <div class='v2-card'>
            <div class='v2-card-label'>223-ФЗ · Разыгранные</div>
            <div class='v2-card-val'>{c223_r}</div>
        </div>
    </div>
    """
    st.markdown(cards_html, unsafe_allow_html=True)

    # 24h new arrivals as compact secondary line
    parts = []
    if kpi.new_24h.fz44_torgi:
        parts.append(f"+{kpi.new_24h.fz44_torgi} 44-ФЗ")
    if kpi.new_24h.fz223_torgi:
        parts.append(f"+{kpi.new_24h.fz223_torgi} 223-ФЗ")
    if kpi.new_24h.fz44_razygranye:
        parts.append(f"+{kpi.new_24h.fz44_razygranye} 44-ФЗ разыгр.")
    if kpi.new_24h.fz223_razygranye:
        parts.append(f"+{kpi.new_24h.fz223_razygranye} 223-ФЗ разыгр.")

    detail = " · ".join(parts) if parts else "нет новых"
    ts = kpi.last_sync_at.strftime(" · Обновлено %d.%m %H:%M") if kpi.last_sync_at else ""

    st.markdown(
        f"<div class='v2-secondary-line'>Новые за 24 часа: <b>{detail}</b>{ts}</div>",
        unsafe_allow_html=True,
    )


# ── Section 2: Document pipeline process strip ───────────────────────────

def _render_pipeline_strip(kpi: DashboardKPI) -> None:
    """Document pipeline as a compact process strip container."""
    st.markdown("<div class='v2-section-title'>ДОКУМЕНТЫ</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='v2-section-caption'>Статус обработки документов по закупкам (все периоды)</div>",
        unsafe_allow_html=True,
    )

    p = kpi.pipeline
    q_val = _fmt(p.queued)
    pr_val = _fmt(p.processing)
    comp_val = _fmt(p.processed)
    err_val = _fmt(p.failed + p.no_links)

    strip_html = f"""
    <div class='v2-pipeline-strip'>
        <div class='v2-pipeline-step'>
            <div class='v2-pipeline-val'>{q_val}</div>
            <div class='v2-pipeline-label'>В очереди</div>
        </div>
        <div class='v2-pipeline-sep'></div>
        <div class='v2-pipeline-step'>
            <div class='v2-pipeline-val'>{pr_val}</div>
            <div class='v2-pipeline-label'>Обрабатывается</div>
        </div>
        <div class='v2-pipeline-sep'></div>
        <div class='v2-pipeline-step'>
            <div class='v2-pipeline-val'>{comp_val}</div>
            <div class='v2-pipeline-label'>Завершено</div>
        </div>
        <div class='v2-pipeline-sep'></div>
        <div class='v2-pipeline-step'>
            <div class='v2-pipeline-val'>{err_val}</div>
            <div class='v2-pipeline-label'>Ошибки / нет документов</div>
        </div>
    </div>
    <div class='v2-secondary-line' style='margin-bottom:12px;'>Все периоды</div>
    """
    st.markdown(strip_html, unsafe_allow_html=True)


# ── Section 3: Commercial assessment quality ─────────────────────────────

def _render_assessment(kpi: DashboardKPI) -> None:
    """Medal transition summary cards, non-zero transition table, and matrix."""
    md = kpi.medals

    st.markdown("<div class='v2-section-title'>КОММЕРЧЕСКАЯ ОЦЕНКА</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='v2-section-caption'>Изменение первоначальной → текущей оценки по коммерческим категориям</div>",
        unsafe_allow_html=True,
    )

    same_cnt = _fmt(md.same)
    same_pct = f"{md.same_pct():.0f}%"
    down_cnt = _fmt(md.down)
    down_pct = f"{md.down_pct():.0f}%"
    up_cnt = _fmt(md.up)
    up_pct = f"{md.up_pct():.0f}%"

    cards_html = f"""
    <div class='v2-kpi-grid-3'>
        <div class='v2-card'>
            <div class='v2-card-label'>Без изменения</div>
            <div class='v2-card-val'>{same_cnt} <span class='v2-card-pct'>· {same_pct}</span></div>
        </div>
        <div class='v2-card'>
            <div class='v2-card-label'>↓ Понижена</div>
            <div class='v2-card-val'>{down_cnt} <span class='v2-card-pct'>· {down_pct}</span></div>
        </div>
        <div class='v2-card'>
            <div class='v2-card-label'>↑ Повышена</div>
            <div class='v2-card-val'>{up_cnt} <span class='v2-card-pct'>· {up_pct}</span></div>
        </div>
    </div>
    """
    st.markdown(cards_html, unsafe_allow_html=True)

    # Invariant warning if violated
    if md.total_decided > 0 and not md.invariant_pass:
        st.warning(
            f"⚠️ Invariant FAIL: "
            f"SAME({md.same}) + DOWN({md.down}) + UP({md.up}) = {md.total_decided} "
            f"≠ matrix({md.matrix_sum})"
        )

    # Transition details under collapsed expander (chart removed from main screen)
    if md.total_decided > 0:
        with st.expander("Подробнее об изменении медалей", expanded=False):
            _render_transition_details_table(kpi)
            with st.expander("Показать полную матрицу (4×4)", expanded=False):
                _render_transition_matrix(kpi)


# ── Transition details: Compact table of non-zero transitions ────────────

def _render_transition_details_table(kpi: DashboardKPI) -> None:
    """Render list of factual non-zero transitions (Было | Стало | Количество)."""
    md = kpi.medals
    grid = md.matrix_grid()

    transitions: List[Tuple[str, str, int]] = []
    for p in MEDAL_RANK:
        for f in MEDAL_RANK:
            cnt = grid.get((p, f), 0)
            if cnt > 0:
                transitions.append((p, f, cnt))

    if not transitions:
        st.caption("Нет переходов для отображения.")
        return

    s_th = "padding:6px 12px;border-bottom:1px solid #cbd5e1;color:#475569;font-weight:600;font-size:12px;text-align:left;"
    s_td = "padding:6px 12px;border-bottom:1px solid #f1f5f9;font-size:13px;"

    html = [
        "<table style='width:100%;max-width:480px;border-collapse:collapse;margin:4px 0 10px 0;'>",
        "<thead><tr>",
        f"<th style='{s_th}'>Было</th>",
        f"<th style='{s_th}'>Стало</th>",
        f"<th style='{s_th}text-align:right;'>Количество</th>",
        "</tr></thead><tbody>",
    ]

    for p, f, cnt in transitions:
        p_c = _MEDAL_COLORS.get(p, "#666")
        f_c = _MEDAL_COLORS.get(f, "#666")
        p_label = f"<span style='color:{p_c};font-weight:600;'>{_MEDAL_EMOJI.get(p, '')} {p}</span>"
        f_label = f"<span style='color:{f_c};font-weight:600;'>{_MEDAL_EMOJI.get(f, '')} {f}</span>"
        arrow = "→" if p != f else "="

        html.append(
            f"<tr>"
            f"<td style='{s_td}'>{p_label}</td>"
            f"<td style='{s_td}'>{arrow} {f_label}</td>"
            f"<td style='{s_td}text-align:right;font-weight:600;'>{_fmt(cnt)}</td>"
            f"</tr>"
        )

    html.append("</tbody></table>")
    st.markdown("".join(html), unsafe_allow_html=True)


# ── 4×4 Transition matrix table ──────────────────────────────────────────

def _render_transition_matrix(kpi: DashboardKPI) -> None:
    """Exact 4×4 transition matrix as a compact HTML table."""
    md = kpi.medals
    grid = md.matrix_grid()

    if md.total_decided == 0:
        return

    s = "border:1px solid #e2e8f0;padding:5px 8px;text-align:center;font-size:12px;"
    html = ['<table style="width:100%;max-width:600px;border-collapse:collapse;margin:4px 0 8px 0;">']

    # Header
    html.append("<tr>")
    html.append(f'<th style="{s}background:#f8fafc;color:#475569;">↓ Нач. \\ Итог. →</th>')
    for f in MEDAL_RANK:
        c = _MEDAL_COLORS.get(f, "#888")
        html.append(f'<th style="{s}background:{c}18;">{_MEDAL_EMOJI.get(f, "")} {f}</th>')
    html.append(f'<th style="{s}background:#f8fafc;font-weight:600;">Σ</th>')
    html.append("</tr>")

    # Rows
    for p in MEDAL_RANK:
        row_t = sum(grid[(p, f)] for f in MEDAL_RANK)
        c = _MEDAL_COLORS.get(p, "#888")
        html.append("<tr>")
        html.append(f'<td style="{s}background:{c}18;font-weight:600;">'
                     f'{_MEDAL_EMOJI.get(p, "")} {p}</td>')
        for f in MEDAL_RANK:
            v = grid[(p, f)]
            bg = ""
            if p == f and v > 0:
                bg = "background:#f0fdf4;font-weight:600;"
            elif v > 0:
                bg = "background:#fffbeb;"
            html.append(f'<td style="{s}{bg}">{_fmt(v) if v > 0 else "—"}</td>')
        html.append(f'<td style="{s}font-weight:600;">{_fmt(row_t)}</td>')
        html.append("</tr>")

    # Footer
    html.append("<tr>")
    html.append(f'<td style="{s}background:#f8fafc;font-weight:600;">Σ</td>')
    for f in MEDAL_RANK:
        ct = sum(grid[(p, f)] for p in MEDAL_RANK)
        html.append(f'<td style="{s}background:#f8fafc;font-weight:600;">{_fmt(ct)}</td>')
    gt = sum(grid[(p, f)] for p in MEDAL_RANK for f in MEDAL_RANK)
    html.append(f'<td style="{s}background:#eff6ff;font-weight:700;">{_fmt(gt)}</td>')
    html.append("</tr></table>")

    st.markdown("".join(html), unsafe_allow_html=True)
