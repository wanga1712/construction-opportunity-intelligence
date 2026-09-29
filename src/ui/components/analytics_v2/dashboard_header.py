"""Dashboard header — business overview of the CRM contour.

Top of the «Аналитический контур V2» page, read top to bottom:

1. ЗАКУПКИ — 44-ФЗ / 223-ФЗ × Идут торги (подача открыта) / Разыграны
2. ЗАГРУЖЕНО В CRM ЗА 24 ЧАСА — 44-ФЗ / 223-ФЗ + новые по дате начала (источник)
3. ДОКУМЕНТЫ        — в очереди / парсится / обработано / ошибка
4. РЕЗУЛЬТАТ МОДЕЛИ — подтверждена / понижена / повышена + матрица переходов

All data comes from ``analytics_dashboard_kpi_service.load_dashboard_kpi()``.

Visual invariants
-----------------
- Bounded container width: ~1220px max, centered horizontally.
- Compact KPI cards (180-250px wide, ~82px tall), never more than 4 per row.
- Large primary number, short Russian business caption, no technical text.
- No table names, worker/service names, enum names or raw exceptions here.
- A failed query renders "Нет данных" with a short warning — never zeros.
  Raw exceptions stay in the logs.
- Full header height ≈ 400-500px on desktop viewports.
"""

from __future__ import annotations

from html import escape
from typing import Any, Dict, List, Tuple

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
.v2-kpi-grid-4 {
    display: grid;
    grid-template-columns: repeat(4, minmax(180px, 1fr));
    gap: 10px;
    margin-bottom: 6px;
}
.v2-kpi-grid-2 {
    display: grid;
    grid-template-columns: repeat(2, minmax(200px, 1fr));
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
@media (max-width: 900px) {
    .v2-kpi-grid-4 {
        grid-template-columns: repeat(2, 1fr);
    }
    .v2-kpi-grid-3 {
        grid-template-columns: 1fr;
    }
}
</style>
"""


# ── DB wrapper ────────────────────────────────────────────────────────────

class _CrmDBWrapper:
    """Minimal DB wrapper providing execute_query() for the KPI service."""

    # The CRM KPI queries are index-only scans over a large table (~2 s warm on
    # S13).  The previous 3 s ceiling turned real numbers into "Нет данных"
    # whenever the server was busy; 30 s keeps them reliable while still failing
    # visibly instead of hanging forever.
    STATEMENT_TIMEOUT_MS = 30000
    CONNECT_TIMEOUT_S = 10

    def execute_query(self, sql: str, params: Any = None, **kw) -> list:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        from src.services.crm_db_runtime import require_crm_db_connect_kwargs

        conn_kwargs = dict(require_crm_db_connect_kwargs())
        conn_kwargs["connect_timeout"] = self.CONNECT_TIMEOUT_S
        conn = psycopg2.connect(**conn_kwargs)
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"SET statement_timeout = {self.STATEMENT_TIMEOUT_MS}")
                cur.execute(sql, params or ())
                return cur.fetchall()
        finally:
            conn.close()


# ── Formatting helpers ────────────────────────────────────────────────────

def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


_NO_DATA = "<span style='font-size:15px;font-weight:600;color:#b45309;'>Нет данных</span>"


def _kpi_value(available: bool, n: int) -> str:
    """Real value, or "Нет данных". A failed query is never shown as 0."""
    return _fmt(n) if available else _NO_DATA


# ── Cached loader ─────────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def _load_cached_dashboard_kpi() -> DashboardKPI:
    """Load the KPI snapshot with bounded query timeouts (cached for 60s)."""
    crm_db = _CrmDBWrapper()

    def _doc_connect():
        import psycopg2
        from src.services.doc_db_runtime import require_doc_db_connect_kwargs

        kwargs = dict(require_doc_db_connect_kwargs())
        kwargs["connect_timeout"] = 5
        conn = psycopg2.connect(**kwargs)
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 15000")
        return conn

    return load_dashboard_kpi(crm_db, doc_db_connect=_doc_connect)


# ── Main entry point ──────────────────────────────────────────────────────

def render_dashboard_header() -> None:
    """Business overview: procurements, new 24h, documents, model result.

    Fail-safe. A section whose query failed renders "Нет данных" with a short
    warning, never zeros. Technical detail belongs in the page-level
    "Техническая информация" expander, not here.
    """
    try:
        kpi = _load_cached_dashboard_kpi()
    except Exception as e:  # noqa: BLE001
        kpi = DashboardKPI()
        kpi.load_error = type(e).__name__

    st.markdown(_COMPACT_DASHBOARD_CSS, unsafe_allow_html=True)
    st.markdown("<div class='v2-dashboard-wrap'>", unsafe_allow_html=True)

    if not (kpi.array_ok or kpi.new_24h_ok or kpi.medals_ok):
        st.error(
            "Нет подключения к базе CRM (S13). Проверьте туннель и повторите "
            "загрузку страницы."
        )

    for section in (_render_inventory, _render_new_24h, _render_documents, _render_assessment):
        try:
            section(kpi)
        except Exception as e:  # noqa: BLE001
            st.warning(f"Раздел временно недоступен ({type(e).__name__}).")

    st.markdown("</div>", unsafe_allow_html=True)


# ── Section 1: Procurement inventory ─────────────────────────────────────

def _render_inventory(kpi: DashboardKPI) -> None:
    """Row 1 — procurement array: 44/223-FZ × torgi/razygranye."""
    st.markdown("<div class='v2-section-title'>Закупки</div>", unsafe_allow_html=True)

    ok = kpi.array_ok
    cards = (
        ("44-ФЗ · Идут торги", kpi.array.fz44_torgi),
        ("223-ФЗ · Идут торги", kpi.array.fz223_torgi),
        ("44-ФЗ · Разыграны", kpi.array.fz44_razygranye),
        ("223-ФЗ · Разыграны", kpi.array.fz223_razygranye),
    )
    html = ["<div class='v2-kpi-grid-4'>"]
    for label, value in cards:
        html.append(
            "<div class='v2-card'>"
            f"<div class='v2-card-label'>{escape(label)}</div>"
            f"<div class='v2-card-val'>{_kpi_value(ok, value)}</div>"
            "</div>"
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)

    if ok:
        st.markdown(
            "<div class='v2-secondary-line'>"
            + escape("Идут торги — подача ещё открыта (до дедлайна не меньше 2 дней).")
            + "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("ЗАКУПКИ: нет данных из базы. Проверьте связь.")


# ── Section 2: New in the last 24 hours ──────────────────────────────────

def _render_new_24h(kpi: DashboardKPI) -> None:
    """Row 2 — CRM ingest of the last 24 hours + source-side arrivals.

    ``crm_created_at`` is the moment the row was written into the CRM
    projection, and mass re-projection rewrites it.  The counters are
    therefore labelled as ingest, never as "new procurements"; genuinely
    new tenders are shown separately by their source start date.
    """
    st.markdown("<div class='v2-section-title'>Загружено в CRM за 24 часа</div>", unsafe_allow_html=True)

    ok = kpi.new_24h_ok
    cards = (
        ("44-ФЗ · загружено", kpi.new_24h.fz44_torgi),
        ("223-ФЗ · загружено", kpi.new_24h.fz223_torgi),
    )
    html = ["<div class='v2-kpi-grid-2'>"]
    for label, value in cards:
        html.append(
            "<div class='v2-card'>"
            f"<div class='v2-card-label'>{escape(label)}</div>"
            f"<div class='v2-card-val'>{_kpi_value(ok, value)}</div>"
            "</div>"
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)

    awarded: List[str] = []
    if kpi.new_24h.fz44_razygranye:
        awarded.append(f"{_fmt(kpi.new_24h.fz44_razygranye)} 44-ФЗ")
    if kpi.new_24h.fz223_razygranye:
        awarded.append(f"{_fmt(kpi.new_24h.fz223_razygranye)} 223-ФЗ")

    bits: List[str] = []
    if ok and awarded:
        bits.append("Разыграны (загружено за 24 ч): " + " · ".join(awarded))
    if kpi.new_by_source_date_ok:
        bits.append(
            "Новых по дате начала (источник): "
            f"{_fmt(kpi.new_by_source_date_1d)} за 24 ч · "
            f"{_fmt(kpi.new_by_source_date_7d)} за 7 дн"
        )
    if kpi.last_sync_ok and kpi.last_sync_at:
        bits.append("Данные обновлены: " + kpi.last_sync_at.strftime("%H:%M"))
    elif not kpi.last_sync_ok:
        bits.append("Время обновления: нет данных")

    if bits:
        st.markdown(
            "<div class='v2-secondary-line'>" + escape(" · ".join(bits)) + "</div>",
            unsafe_allow_html=True,
        )
    if not ok:
        st.caption("ЗАГРУЖЕНО В CRM ЗА 24 ЧАСА: нет данных из базы. Проверьте связь.")


# ── Section 3: Document pipeline ─────────────────────────────────────────

def _render_documents(kpi: DashboardKPI) -> None:
    """Row 3 — document pipeline, real document_processing_queue statuses."""
    st.markdown("<div class='v2-section-title'>Документы</div>", unsafe_allow_html=True)

    ok = kpi.pipeline_ok
    p = kpi.pipeline
    cards = (
        ("В очереди", p.queued),
        ("Парсится", p.processing),
        ("Обработано", p.processed),
        ("Ошибка / нет документов", p.failed + p.no_links),
    )
    html = ["<div class='v2-kpi-grid-4'>"]
    for label, value in cards:
        html.append(
            "<div class='v2-card'>"
            f"<div class='v2-card-label'>{escape(label)}</div>"
            f"<div class='v2-card-val'>{_kpi_value(ok, value)}</div>"
            "</div>"
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)

    if not ok:
        st.caption("ДОКУМЕНТЫ: нет данных из базы. Проверьте связь.")


# ── Section 4: Commercial assessment quality ─────────────────────────────

def _render_assessment(kpi: DashboardKPI) -> None:
    """Row 4 — model outcome per CATEGORY OPPORTUNITY + 4×4 medal matrix."""
    md = kpi.medals
    st.markdown("<div class='v2-section-title'>Результат модели</div>", unsafe_allow_html=True)

    if not kpi.medals_ok:
        st.markdown(
            "<div class='v2-kpi-grid-3'>"
            + "".join(
                "<div class='v2-card'>"
                f"<div class='v2-card-label'>{escape(label)}</div>"
                f"<div class='v2-card-val'>{_NO_DATA}</div>"
                "</div>"
                for label in ("Подтверждена", "Понижена", "Повышена")
            )
            + "</div>",
            unsafe_allow_html=True,
        )
        st.caption("РЕЗУЛЬТАТ МОДЕЛИ: нет данных из базы. Проверьте связь.")
        return

    decided = md.total_decided
    cards = (
        ("Подтверждена", md.same, md.same_pct()),
        ("Понижена", md.down, md.down_pct()),
        ("Повышена", md.up, md.up_pct()),
    )
    html = ["<div class='v2-kpi-grid-3'>"]
    for label, cnt, pct in cards:
        pct_html = f"<span class='v2-card-pct'>· {pct:.0f}%</span>" if decided else ""
        html.append(
            "<div class='v2-card'>"
            f"<div class='v2-card-label'>{escape(label)}</div>"
            f"<div class='v2-card-val'>{_fmt(cnt)} {pct_html}</div>"
            "</div>"
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)

    if decided == 0:
        st.caption("Пока нет подтверждённых медалей.")
        return

    if not md.invariant_pass:
        st.caption("Инвариант переходов не сходится — возможна задержка обновления данных.")

    st.caption("Точная матрица переходов: строка — начальная медаль, столбец — итоговая.")
    _render_transition_matrix(kpi)

    with st.expander("Подробные переходы", expanded=False):
        _render_transition_details_table(kpi)


# ── Transition details: compact table of non-zero transitions ────────────

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

    html.append("<tr>")
    html.append(f'<th style="{s}background:#f8fafc;color:#475569;">Было \\ Стало</th>')
    for f in MEDAL_RANK:
        c = _MEDAL_COLORS.get(f, "#888")
        html.append(f'<th style="{s}background:{c}18;">{_MEDAL_EMOJI.get(f, "")} {f}</th>')
    html.append(f'<th style="{s}background:#f8fafc;font-weight:600;">Σ</th>')
    html.append("</tr>")

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

    html.append("<tr>")
    html.append(f'<td style="{s}background:#f8fafc;font-weight:600;">Σ</td>')
    for f in MEDAL_RANK:
        ct = sum(grid[(p, f)] for p in MEDAL_RANK)
        html.append(f'<td style="{s}background:#f8fafc;font-weight:600;">{_fmt(ct)}</td>')
    gt = sum(grid[(p, f)] for p in MEDAL_RANK for f in MEDAL_RANK)
    html.append(f'<td style="{s}background:#eff6ff;font-weight:700;">{_fmt(gt)}</td>')
    html.append("</tr></table>")

    st.markdown("".join(html), unsafe_allow_html=True)
