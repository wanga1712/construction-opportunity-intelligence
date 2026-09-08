"""Dashboard header — factual KPI rows and medal transition chart.

Renders 4 metric rows + transition chart/matrix, replacing mock_data KPIs.
All data comes from analytics_dashboard_kpi_service.load_dashboard_kpi().

Rows
----
1. Array counts: 44-ФЗ/223-ФЗ × Идут торги / Разыгранные
2. New in 24h (rolling via crm_created_at)
3. Document pipeline: В ОЧЕРЕДИ / ПАРСИТСЯ / ОБРАБОТАНО / ОТКЛОНЕНО
4. Medal decisions: ✓ ПОДТВЕРЖДЕНА / ↓ ПОНИЖЕНА / ↑ ПОВЫШЕНА

Chart
-----
100% stacked horizontal bars: preliminary → final medal breakdown
4×4 transition matrix table below
"""

from __future__ import annotations

from typing import Any, Optional

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


# ── DB wrapper (matches tabs.py / card_processing.py pattern) ─────────────

class _CrmDBWrapper:
    """Minimal DB wrapper providing execute_query() for the KPI service.

    Uses psycopg2 directly via require_crm_db_connect_kwargs(),
    matching the existing pattern in tabs.py and card_processing.py.
    """

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
    """Render the full dashboard header with factual KPIs.

    DB connections are created internally using the same pattern as tabs.py
    and card_processing.py (require_crm_db_connect_kwargs).
    """
    crm_db = _CrmDBWrapper()

    def _doc_connect():
        import psycopg2
        from src.services.crm_db_runtime import require_crm_db_connect_kwargs
        kwargs = dict(require_crm_db_connect_kwargs())
        kwargs["dbname"] = "document_intelligence"
        kwargs["connect_timeout"] = 5
        return psycopg2.connect(**kwargs)

    kpi = load_dashboard_kpi(crm_db, doc_db_connect=_doc_connect)


    _render_array_row(kpi)
    _render_new_24h_row(kpi)
    st.divider()
    _render_pipeline_row(kpi)
    st.divider()
    _render_medal_row(kpi)
    _render_transition_chart(kpi)
    _render_transition_matrix(kpi)

    # Query diagnostics (collapsed)
    with st.expander("📊 Диагностика запросов", expanded=False):
        st.caption(
            f"Запросов: {kpi.query_count} · "
            f"Время: {kpi.query_time_ms:.0f} мс · "
            f"SOURCE_GAP: {', '.join(kpi.source_gaps) if kpi.source_gaps else 'нет'}"
        )


# ── Row 1: Array counts ──────────────────────────────────────────────────

def _render_array_row(kpi: DashboardKPI) -> None:
    """4 metrics: 44-ФЗ/223-ФЗ × torgi/razygranye."""
    st.markdown("##### Массив закупок")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("44-ФЗ · Идут торги", f"{kpi.array.fz44_torgi:,}".replace(",", " "))
    c2.metric("223-ФЗ · Идут торги", f"{kpi.array.fz223_torgi:,}".replace(",", " "))
    c3.metric("44-ФЗ · Разыгранные", f"{kpi.array.fz44_razygranye:,}".replace(",", " "))
    c4.metric("223-ФЗ · Разыгранные", f"{kpi.array.fz223_razygranye:,}".replace(",", " "))


# ── Row 2: New in 24h ────────────────────────────────────────────────────

def _render_new_24h_row(kpi: DashboardKPI) -> None:
    """New procurements in rolling 24h window."""
    ts_label = ""
    if kpi.last_sync_at is not None:
        ts_label = kpi.last_sync_at.strftime("%Y-%m-%d %H:%M MSK")

    st.markdown(f"##### Новые за последние 24 часа {'· ' + ts_label if ts_label else ''}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("44-ФЗ · Идут торги", kpi.new_24h.fz44_torgi)
    c2.metric("223-ФЗ · Идут торги", kpi.new_24h.fz223_torgi)
    c3.metric("44-ФЗ · Разыгранные", kpi.new_24h.fz44_razygranye)
    c4.metric("223-ФЗ · Разыгранные", kpi.new_24h.fz223_razygranye)


# ── Row 3: Document pipeline ─────────────────────────────────────────────

def _render_pipeline_row(kpi: DashboardKPI) -> None:
    """Document processing queue status counts."""
    st.markdown("##### Документальный pipeline")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("В ОЧЕРЕДИ", f"{kpi.pipeline.queued:,}".replace(",", " "))
    c2.metric("ПАРСИТСЯ", kpi.pipeline.processing)
    c3.metric("ОБРАБОТАНО", kpi.pipeline.processed)

    # ОТКЛОНЕНО is SOURCE_GAP — show technical failure counts instead
    failed_total = kpi.pipeline.failed + kpi.pipeline.no_links
    if kpi.pipeline.rejected_available:
        c4.metric("ОТКЛОНЕНО", failed_total)
    else:
        c4.metric(
            "Ошибки / Нет ссылок",
            failed_total,
            help="ОТКЛОНЕНО = SOURCE_GAP: в pipeline нет статуса «документы не подтвердили "
                 "коммерческую возможность». Показаны FAILED + NO_LINKS.",
        )


# ── Row 4: Medal decisions ───────────────────────────────────────────────

def _render_medal_row(kpi: DashboardKPI) -> None:
    """Medal transition summary: SAME / DOWN / UP."""
    md = kpi.medals
    st.markdown("##### Медальные решения (по category opportunity)")
    c1, c2, c3 = st.columns(3)

    def _fmt(count: int, pct: float) -> str:
        return f"{count}  ({pct:.1f}%)"

    c1.metric("✓ ПОДТВЕРЖДЕНА", _fmt(md.same, md.same_pct()))
    c2.metric("↓ ПОНИЖЕНА", _fmt(md.down, md.down_pct()))
    c3.metric("↑ ПОВЫШЕНА", _fmt(md.up, md.up_pct()))

    if md.rejected > 0:
        st.caption(f"Отклонено (вне матрицы): {md.rejected}")

    # Invariant check
    if md.total_decided > 0 and not md.invariant_pass:
        st.warning(
            f"⚠️ Transition invariant FAIL: "
            f"SAME({md.same}) + DOWN({md.down}) + UP({md.up}) = {md.total_decided} "
            f"≠ matrix_sum({md.matrix_sum})"
        )


# ── Chart: Stacked horizontal bars ───────────────────────────────────────

def _render_transition_chart(kpi: DashboardKPI) -> None:
    """100% stacked horizontal bar chart of medal transitions."""
    md = kpi.medals
    grid = md.matrix_grid()

    # Check if there's any data
    if md.total_decided == 0:
        st.info("Нет данных для графика переходов медалей.")
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
            title="Переходы медалей (100%)",
            xaxis_title="% от начального уровня",
            yaxis_title="Начальная медаль",
            height=250,
            margin=dict(l=0, r=0, t=40, b=30),
            legend=dict(orientation="h", y=-0.15),
            xaxis=dict(range=[0, 100], dtick=25),
        )

        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        st.warning("Plotly не установлен — график переходов недоступен.")


# ── 4×4 Transition matrix table ──────────────────────────────────────────

def _render_transition_matrix(kpi: DashboardKPI) -> None:
    """Exact 4×4 transition matrix as an HTML table."""
    md = kpi.medals
    grid = md.matrix_grid()

    if md.total_decided == 0:
        return

    st.markdown("##### Точная матрица переходов")

    # Build HTML table
    html = ['<table style="width:100%; border-collapse:collapse; font-size:14px;">']

    # Header row
    html.append("<tr>")
    html.append('<th style="border:1px solid #ddd; padding:6px; background:#f5f5f5;">↓ Начальная \\ Итоговая →</th>')
    for f in MEDAL_RANK:
        color = _MEDAL_COLORS.get(f, "#888")
        html.append(
            f'<th style="border:1px solid #ddd; padding:6px; background:{color}20; '
            f'text-align:center;">{_MEDAL_EMOJI.get(f, "")} {f}</th>'
        )
    html.append('<th style="border:1px solid #ddd; padding:6px; background:#f5f5f5; text-align:center;">Σ</th>')
    html.append("</tr>")

    # Data rows
    for p in MEDAL_RANK:
        row_total = sum(grid[(p, f)] for f in MEDAL_RANK)
        html.append("<tr>")
        color = _MEDAL_COLORS.get(p, "#888")
        html.append(
            f'<td style="border:1px solid #ddd; padding:6px; background:{color}20; '
            f'font-weight:bold;">{_MEDAL_EMOJI.get(p, "")} {p}</td>'
        )
        for f in MEDAL_RANK:
            val = grid[(p, f)]
            cell_style = "border:1px solid #ddd; padding:6px; text-align:center;"
            if p == f and val > 0:
                cell_style += " font-weight:bold; background:#e8f5e9;"
            elif val > 0:
                cell_style += " background:#fff3e0;"
            html.append(f'<td style="{cell_style}">{val if val > 0 else "—"}</td>')
        html.append(
            f'<td style="border:1px solid #ddd; padding:6px; text-align:center; '
            f'font-weight:bold;">{row_total}</td>'
        )
        html.append("</tr>")

    # Footer: column totals
    html.append("<tr>")
    html.append(
        '<td style="border:1px solid #ddd; padding:6px; background:#f5f5f5; '
        'font-weight:bold;">Σ</td>'
    )
    for f in MEDAL_RANK:
        col_total = sum(grid[(p, f)] for p in MEDAL_RANK)
        html.append(
            f'<td style="border:1px solid #ddd; padding:6px; text-align:center; '
            f'background:#f5f5f5; font-weight:bold;">{col_total}</td>'
        )
    grand_total = sum(grid[(p, f)] for p in MEDAL_RANK for f in MEDAL_RANK)
    html.append(
        f'<td style="border:1px solid #ddd; padding:6px; text-align:center; '
        f'background:#e3f2fd; font-weight:bold;">{grand_total}</td>'
    )
    html.append("</tr>")

    html.append("</table>")
    st.markdown("".join(html), unsafe_allow_html=True)
