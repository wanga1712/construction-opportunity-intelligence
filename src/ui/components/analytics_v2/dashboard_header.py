"""Dashboard header — factual KPI summary, compact layout.

Renders procurement inventory, new arrivals, document pipeline status,
and commercial assessment quality in a single viewport-friendly header.
All data from analytics_dashboard_kpi_service.load_dashboard_kpi().

Semantic rules
--------------
- Medal SAME/DOWN/UP compares candidate_initial_medal vs current_effective_medal.
  This does NOT prove document or expert confirmation.
- "ЗАВЕРШЕНО" = document_processing_queue status COMPLETED.
  Does not automatically confirm a commercial medal.
- SOURCE_GAP: MEDAL_DOCUMENT_PROVENANCE — no factual link between medal
  transitions and document processing completion in current schema.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from src.services.analytics_dashboard_kpi_service import (
    MEDAL_RANK,
    DashboardKPI,
    load_dashboard_kpi,
)

# ── Medal colors ──────────────────────────────────────────────────────────

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

# ── Compact CSS ───────────────────────────────────────────────────────────

_COMPACT_CSS = """
<style>
div[data-testid="stMetric"] {
    padding: 0.25rem 0;
}
div[data-testid="stMetric"] label {
    font-size: 0.78rem;
}
div[data-testid="stMetric"] [data-testid="stMetricValue"] {
    font-size: 1.3rem;
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


# ── Main entry point ─────────────────────────────────────────────────────

def render_dashboard_header() -> None:
    """Render the full dashboard header — compact, semantically correct."""
    crm_db = _CrmDBWrapper()

    def _doc_connect():
        import psycopg2
        from src.services.crm_db_runtime import require_crm_db_connect_kwargs
        kwargs = dict(require_crm_db_connect_kwargs())
        kwargs["dbname"] = "document_intelligence"
        kwargs["connect_timeout"] = 5
        return psycopg2.connect(**kwargs)

    kpi = load_dashboard_kpi(crm_db, doc_db_connect=_doc_connect)

    st.markdown(_COMPACT_CSS, unsafe_allow_html=True)
    _render_inventory(kpi)
    _render_pipeline_strip(kpi)
    _render_assessment(kpi)

    with st.expander("🔍 Диагностика", expanded=False):
        st.caption(
            f"Запросов: {kpi.query_count} · "
            f"Время: {kpi.query_time_ms:.0f} мс · "
            f"SOURCE_GAP: {', '.join(kpi.source_gaps) if kpi.source_gaps else '—'}"
        )


# ── Section 1: Procurement inventory + new arrivals ──────────────────────

def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _render_inventory(kpi: DashboardKPI) -> None:
    """Procurement counts and 24h new arrivals in compact layout."""
    st.markdown("##### Массив закупок")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("44-ФЗ · Торги", _fmt(kpi.array.fz44_torgi))
    c2.metric("223-ФЗ · Торги", _fmt(kpi.array.fz223_torgi))
    c3.metric("44-ФЗ · Разыгранные", _fmt(kpi.array.fz44_razygranye))
    c4.metric("223-ФЗ · Разыгранные", _fmt(kpi.array.fz223_razygranye))

    # New 24h — secondary compact row, scoped to procurement arrivals only
    ts = ""
    if kpi.last_sync_at is not None:
        ts = kpi.last_sync_at.strftime(" · %d.%m %H:%M")
    total_new = (
        kpi.new_24h.fz44_torgi + kpi.new_24h.fz223_torgi
        + kpi.new_24h.fz44_razygranye + kpi.new_24h.fz223_razygranye
    )
    parts = []
    if kpi.new_24h.fz44_torgi:
        parts.append(f"44-ФЗ торги: +{kpi.new_24h.fz44_torgi}")
    if kpi.new_24h.fz223_torgi:
        parts.append(f"223-ФЗ торги: +{kpi.new_24h.fz223_torgi}")
    if kpi.new_24h.fz44_razygranye:
        parts.append(f"44-ФЗ разыгр.: +{kpi.new_24h.fz44_razygranye}")
    if kpi.new_24h.fz223_razygranye:
        parts.append(f"223-ФЗ разыгр.: +{kpi.new_24h.fz223_razygranye}")
    detail = " · ".join(parts) if parts else "нет новых"
    st.caption(f"Новые за 24 ч (поступление закупок): **+{total_new}** — {detail}{ts}")


# ── Section 2: Document pipeline — horizontal strip ──────────────────────

def _render_pipeline_strip(kpi: DashboardKPI) -> None:
    """Document pipeline as compact horizontal process strip."""
    st.markdown("##### Документальный конвейер")
    st.caption("Статус обработки документов по закупкам (все периоды)")

    p = kpi.pipeline
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("В очереди", _fmt(p.queued))
    c2.metric("Обрабатывается", p.processing)
    c3.metric(
        "Завершено",
        p.processed,
        help=(
            "Количество записей document_processing_queue "
            "со статусом COMPLETED. Не означает автоматически "
            "подтверждение коммерческой медали."
        ),
    )
    tech = p.failed + p.no_links
    c4.metric(
        "Ошибки / нет документов",
        tech,
        help=f"FAILED: {p.failed} · NO_LINKS: {p.no_links}",
    )


# ── Section 3: Commercial assessment quality ─────────────────────────────

def _render_assessment(kpi: DashboardKPI) -> None:
    """Medal transition summary, chart, and matrix."""
    md = kpi.medals

    st.markdown("##### Изменение коммерческой оценки")
    st.caption("Считается по коммерческим категориям закупок")

    # Three compact counters
    c1, c2, c3 = st.columns(3)

    def _mpct(count: int, pct: float) -> str:
        return f"{count}  ({pct:.0f}%)"

    c1.metric(
        "Без изменения",
        _mpct(md.same, md.same_pct()),
        help="Начальная и текущая коммерческая оценка совпадают",
    )
    c2.metric(
        "↓ Понижена",
        _mpct(md.down, md.down_pct()),
        help="Текущая оценка ниже начальной",
    )
    c3.metric(
        "↑ Повышена",
        _mpct(md.up, md.up_pct()),
        help="Текущая оценка выше начальной",
    )

    if md.rejected > 0:
        st.caption(f"Отклонено (вне матрицы): {md.rejected}")

    # Invariant check
    if md.total_decided > 0 and not md.invariant_pass:
        st.warning(
            f"⚠️ Invariant FAIL: "
            f"SAME({md.same}) + DOWN({md.down}) + UP({md.up}) = {md.total_decided} "
            f"≠ matrix({md.matrix_sum})"
        )

    # Transition chart — compact
    _render_transition_chart(kpi)

    # Matrix — collapsed by default
    if md.total_decided > 0:
        with st.expander("Матрица переходов (4×4)", expanded=False):
            _render_transition_matrix(kpi)


# ── Chart: Stacked horizontal bars ───────────────────────────────────────

def _render_transition_chart(kpi: DashboardKPI) -> None:
    """Compact 100% stacked horizontal bar chart of medal transitions."""
    md = kpi.medals
    grid = md.matrix_grid()

    if md.total_decided == 0:
        return

    try:
        import plotly.graph_objects as go

        fig = go.Figure()

        for final_medal in reversed(MEDAL_RANK):
            x_vals = []
            y_vals = []
            for prelim_medal in MEDAL_RANK:
                total_from_prelim = sum(grid[(prelim_medal, f)] for f in MEDAL_RANK)
                if total_from_prelim > 0:
                    pct = grid[(prelim_medal, final_medal)] / total_from_prelim * 100
                else:
                    pct = 0
                x_vals.append(pct)
                y_vals.append(f"{_MEDAL_EMOJI.get(prelim_medal, '')} {prelim_medal}")

            fig.add_trace(go.Bar(
                name=f"→ {final_medal}",
                x=x_vals,
                y=y_vals,
                orientation="h",
                marker_color=_MEDAL_COLORS.get(final_medal, "#888"),
                text=[f"{v:.0f}%" if v > 3 else "" for v in x_vals],
                textposition="inside",
                hovertemplate=(
                    "%{y} → " + final_medal + ": %{x:.1f}%<extra></extra>"
                ),
            ))

        fig.update_layout(
            barmode="stack",
            xaxis_title="% от начального уровня",
            height=180,
            margin=dict(l=0, r=0, t=8, b=24),
            legend=dict(orientation="h", y=-0.25, font=dict(size=11)),
            xaxis=dict(range=[0, 100], dtick=25),
            showlegend=True,
        )

        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        st.caption("Plotly не установлен — график недоступен.")


# ── 4×4 Transition matrix table ──────────────────────────────────────────

def _render_transition_matrix(kpi: DashboardKPI) -> None:
    """Exact 4×4 transition matrix as a compact HTML table."""
    md = kpi.medals
    grid = md.matrix_grid()

    if md.total_decided == 0:
        return

    s = "border:1px solid #ddd;padding:4px;text-align:center;font-size:13px;"
    html = [f'<table style="width:100%;border-collapse:collapse;">']

    # Header
    html.append("<tr>")
    html.append(f'<th style="{s}background:#f5f5f5;">↓ Нач. \\ Итог. →</th>')
    for f in MEDAL_RANK:
        c = _MEDAL_COLORS.get(f, "#888")
        html.append(f'<th style="{s}background:{c}20;">{_MEDAL_EMOJI.get(f, "")} {f}</th>')
    html.append(f'<th style="{s}background:#f5f5f5;">Σ</th>')
    html.append("</tr>")

    # Rows
    for p in MEDAL_RANK:
        row_t = sum(grid[(p, f)] for f in MEDAL_RANK)
        c = _MEDAL_COLORS.get(p, "#888")
        html.append("<tr>")
        html.append(f'<td style="{s}background:{c}20;font-weight:bold;">'
                     f'{_MEDAL_EMOJI.get(p, "")} {p}</td>')
        for f in MEDAL_RANK:
            v = grid[(p, f)]
            bg = ""
            if p == f and v > 0:
                bg = "background:#e8f5e9;font-weight:bold;"
            elif v > 0:
                bg = "background:#fff3e0;"
            html.append(f'<td style="{s}{bg}">{v if v > 0 else "—"}</td>')
        html.append(f'<td style="{s}font-weight:bold;">{row_t}</td>')
        html.append("</tr>")

    # Footer
    html.append("<tr>")
    html.append(f'<td style="{s}background:#f5f5f5;font-weight:bold;">Σ</td>')
    for f in MEDAL_RANK:
        ct = sum(grid[(p, f)] for p in MEDAL_RANK)
        html.append(f'<td style="{s}background:#f5f5f5;font-weight:bold;">{ct}</td>')
    gt = sum(grid[(p, f)] for p in MEDAL_RANK for f in MEDAL_RANK)
    html.append(f'<td style="{s}background:#e3f2fd;font-weight:bold;">{gt}</td>')
    html.append("</tr></table>")

    st.markdown("".join(html), unsafe_allow_html=True)
