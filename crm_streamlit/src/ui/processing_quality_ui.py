"""Processing quality dashboard — rendered as a tab in the infrastructure page."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import streamlit as st

from src.services.processing_quality import (
    CATEGORY_AWARDED,
    CATEGORY_COMMISSION,
    CATEGORY_OPEN,
    WARN_DOMINANT_CATEGORY,
    WARN_EVIDENCE_SPIKE,
    WARN_HIGH_NO_LINKS,
    WARN_OPEN_STARVED,
    WARN_STUCK_PROCESSING,
    compute_quality_metrics,
    get_daily_matches,
    get_daily_stats,
    get_queue_snapshot,
    get_stuck_processing,
)

_LANE_LABELS = {
    "crm_active_hot": "CRM Hot",
    "open_active": "Open Active",
    "awarded_recent": "Awarded Recent",
    "retry": "Retry",
    "historical_awarded": "Hist. Awarded",
    "unknown": "Неизв.",
}

_STATUS_EMOJI = {
    "pending": "⏳",
    "processing": "⚙️",
    "completed": "✅",
    "no_links": "🔗",
    "error": "❌",
    "sales_window_expired": "⌛",
}

_WARN_ICONS = {
    WARN_HIGH_NO_LINKS: "🔗",
    WARN_DOMINANT_CATEGORY: "⚠️",
    WARN_OPEN_STARVED: "📉",
    WARN_EVIDENCE_SPIKE: "📈",
    WARN_STUCK_PROCESSING: "🔄",
}


def _fmt_rate(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def _fmt_float(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def render_processing_quality_tab(tender_db) -> None:
    """Render the full processing quality dashboard."""
    st.markdown("### Качество обработки закупок")

    # Date selector — default yesterday
    yesterday = date.today() - timedelta(days=1)
    selected_day = st.date_input(
        "Дата анализа",
        value=yesterday,
        max_value=date.today(),
        key="pq_selected_day",
    )

    if st.button("↻ Обновить данные", key="pq_refresh"):
        for key in list(st.session_state.keys()):
            if key.startswith("pq_cache_"):
                del st.session_state[key]
        st.rerun()

    _render_queue_snapshot(tender_db)
    st.divider()
    _render_daily_results(tender_db, selected_day)


def _render_queue_snapshot(tender_db) -> None:
    st.markdown("#### Текущая очередь")

    snap = get_queue_snapshot(tender_db)
    if not snap.get("ok"):
        st.error(f"Очередь недоступна: {snap.get('error')}")
        return

    by_status = snap.get("by_status") or {}
    by_lane = snap.get("by_lane") or {}
    by_source = snap.get("by_source") or {}
    workers = snap.get("active_workers") or []

    pending = by_status.get("pending", 0)
    processing = by_status.get("processing", 0)

    # Top-line metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("⏳ Pending", pending)
    col2.metric("⚙️ Processing", processing)
    col3.metric("👷 Активных workers", len(workers))
    col4.metric("Всего в очереди", sum(by_status.values()))

    if workers:
        st.caption(f"Worker IDs: {', '.join(str(w) for w in workers)}")

    row2_a, row2_b = st.columns(2)

    with row2_a:
        st.markdown("**По lane** (pending + processing)")
        if by_lane:
            for lane, cnt in sorted(by_lane.items(), key=lambda x: -x[1]):
                label = _LANE_LABELS.get(lane, lane)
                st.write(f"- {label}: **{cnt}**")
        else:
            st.caption("Нет данных")

    with row2_b:
        st.markdown("**По источнику** (pending + processing)")
        if by_source:
            for src, cnt in sorted(by_source.items(), key=lambda x: -x[1]):
                st.write(f"- {src}: **{cnt}**")
        else:
            st.caption("Нет данных")


def _render_daily_results(tender_db, selected_day: date) -> None:
    st.markdown(f"#### Итоги за {selected_day.strftime('%d.%m.%Y')}")

    daily = get_daily_stats(tender_db, selected_day)
    if not daily.get("ok"):
        st.error(f"Ошибка запроса: {daily.get('error')}")
        return

    match_result = get_daily_matches(tender_db, selected_day)
    stuck_result = get_stuck_processing(tender_db)
    match_rows = match_result.get("rows")  # None = table/column unavailable

    status_by_category = daily.get("status_by_category") or {}
    stuck_count = stuck_result.get("count") or 0

    metrics = compute_quality_metrics(
        status_by_category=status_by_category,
        match_rows=match_rows,
        stuck_count=stuck_count,
    )

    # Warnings — show first
    if metrics.warnings:
        with st.expander(f"⚠️ Предупреждения: {len(metrics.warnings)}", expanded=True):
            for w in metrics.warnings:
                icon = _WARN_ICONS.get(w.code, "⚠️")
                st.warning(f"{icon} {w.message}")

    # Summary row
    cols = st.columns(5)
    cols[0].metric("✅ Completed", metrics.completed)
    cols[1].metric("🔗 No links", metrics.no_links)
    cols[2].metric("❌ Error", metrics.error)
    cols[3].metric("⌛ Expired", metrics.expired)
    cols[4].metric("Итого финальных", metrics.total_terminal)

    # Quality rates
    st.markdown("##### Показатели качества")
    qcols = st.columns(4)
    qcols[0].metric("no_links rate", _fmt_rate(metrics.no_links_rate))
    qcols[1].metric("error rate", _fmt_rate(metrics.error_rate))
    qcols[2].metric(
        "matches / задача",
        _fmt_float(metrics.matches_per_task),
        help=None if metrics.match_data_available else "Данные недоступны",
    )
    qcols[3].metric(
        "evidence / match",
        _fmt_float(metrics.evidence_per_match),
        help=None if metrics.match_data_available else "Данные недоступны",
    )

    if not metrics.match_data_available:
        st.caption("ℹ️ Данные о matches/evidence недоступны (нет столбца created_at в tender_document_matches или таблица пуста за эту дату)")

    # Category breakdown
    st.markdown("##### Разбивка по типу источника")
    st.caption("COMPUTERS профиль не определяется по данным очереди (нет колонки profile в document_processing_queue)")

    if metrics.by_category:
        cat_order = [CATEGORY_OPEN, CATEGORY_AWARDED, CATEGORY_COMMISSION]
        # Add any other categories (OTHER or unexpected)
        extra = [c for c in metrics.by_category if c not in cat_order]
        ordered_cats = cat_order + extra

        cat_cols = st.columns(len(ordered_cats) or 1)
        for col, cat in zip(cat_cols, ordered_cats):
            cnt = metrics.by_category.get(cat, 0)
            share = metrics.category_shares.get(cat, 0.0)
            col.metric(cat, cnt, f"{share*100:.1f}%")

        # Match breakdown by registry_type if available
        if match_rows:
            st.markdown("**Matches по типу реестра:**")
            match_data = [
                {
                    "Реестр": r.get("registry_type") or "—",
                    "Закупок с matches": r.get("tender_count") or 0,
                    "Matches": r.get("match_count") or 0,
                    "Evidence": r.get("evidence_count") or 0,
                }
                for r in match_rows
            ]
            if match_data:
                st.dataframe(match_data, use_container_width=True, hide_index=True)
    else:
        st.info(f"За {selected_day.strftime('%d.%m.%Y')} финальных записей не найдено.")
