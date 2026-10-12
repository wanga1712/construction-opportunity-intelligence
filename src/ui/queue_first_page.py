"""Queue-first first screen of the analytics contour.

The first meaningful render shows «Очередь возможностей»: a bounded page of the
real commercial queue read straight from production truth. Every heavy section
(KPI, charts, lifecycle worksets, category hierarchy, documents, AI) is moved
behind an explicit open.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from src.services import queue_first_service as qsvc
from src.services import pipeline_observability as pov
from src.ui.components.queue_first.queue_cards import (
    render_card_detail,
    render_queue_card,
)
from src.ui.components.queue_first.pipeline_line import render_pipeline_line


@st.cache_resource(show_spinner=False)
def _doc_conn():
    return qsvc.open_doc_connection()


@st.cache_resource(show_spinner=False)
def _crm_conn():
    return qsvc.open_crm_connection()


def _live_conn(getter):
    conn = getter()
    try:
        if getattr(conn, "closed", 0):
            getter.clear()
            conn = getter()
    except Exception:  # noqa: BLE001
        getter.clear()
        conn = getter()
    return conn


def render_queue_first_page(service=None) -> None:
    st.title("Очередь возможностей")
    st.caption(
        "Первая лента — реальная коммерческая очередь: "
        "document_processing_queue S13_V4 + admission ELIGIBLE. "
        "UI читает готовый production truth и ничего не пересчитывает."
    )
    render_pipeline_line(_pipeline_line())

    crm_conn = _live_conn(_crm_conn)
    filters = _render_filters(crm_conn)
    page = _load_page(filters, crm_conn)
    _render_metrics(page)
    _render_snapshot(crm_conn)

    if not page.cards:
        st.warning("По текущим фильтрам карточки не найдены.")
    for index, card in enumerate(page.cards, start=1):
        render_queue_card(card, index=index, key_prefix="qfirst")
        if st.session_state.get("qfirst_open_id") == card.procurement_id:
            _render_open_card(card, crm_conn)

    _render_pagination(page)
    st.divider()
    _render_analytics_gate()


# ── Filters ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=600, show_spinner=False)
def _category_options() -> List[Dict[str, str]]:
    return qsvc.load_category_options()


def _render_filters(crm_conn) -> qsvc.QueueFilters:
    col1, col2, col3 = st.columns(3)
    with col1:
        medal = st.segmented_control(
            "Медаль", ["ALL", "GOLD", "SILVER", "BRONZE", "WOOD"],
            default="ALL", selection_mode="single", key="qfirst_medal",
        )
    with col2:
        lifecycle = st.segmented_control(
            "Lifecycle", ["ALL", "OPEN", "AWARDED"],
            default="ALL", selection_mode="single", key="qfirst_lifecycle",
        )
    with col3:
        scope = st.segmented_control(
            "Scope", ["ALL", "DIRECT", "WORKS", "DESIGN"],
            default="ALL", selection_mode="single", key="qfirst_scope",
        )

    col4, col5 = st.columns([2, 1])
    categories = _category_options()
    cat_codes = [c["code"] for c in categories]
    cat_names = {c["code"]: c["name"] for c in categories}
    with col4:
        category = st.selectbox(
            "Категория", ["ALL"] + cat_codes,
            format_func=lambda v: "Все категории" if v == "ALL" else f"{cat_names.get(v, v)} ({v})",
            key="qfirst_category",
        )
    with col5:
        use_region = st.toggle("Фильтр по региону", key="qfirst_use_region")
    region = None
    if use_region:
        regions = st.cache_data(ttl=600, show_spinner=False)(qsvc.load_region_options)()
        region = st.selectbox("Регион", ["ALL"] + regions, key="qfirst_region")
        if region == "ALL":
            region = None

    filters = qsvc.QueueFilters(
        medal=None if medal in (None, "ALL") else medal,
        lifecycle=None if lifecycle in (None, "ALL") else lifecycle,
        scope=None if scope in (None, "ALL") else scope,
        category=None if category == "ALL" else category,
        region=region,
    )
    sig = (filters.medal, filters.lifecycle, filters.scope, filters.category, filters.region)
    if st.session_state.get("qfirst_filter_sig") != sig:
        st.session_state.qfirst_filter_sig = sig
        st.session_state.qfirst_start_cursor = None
        st.session_state.qfirst_cursor_stack = []
        st.session_state.pop("qfirst_page_cache", None)
    return filters


# ── Page cache / pagination ─────────────────────────────────────────────────

def _load_page(filters: qsvc.QueueFilters, crm_conn) -> qsvc.QueuePage:
    cursor = st.session_state.get("qfirst_start_cursor")
    sig = (cursor, filters.medal, filters.lifecycle, filters.scope, filters.category, filters.region)
    cached = st.session_state.get("qfirst_page_cache")
    if cached and cached.get("sig") == sig:
        return cached["page"]
    t0 = time.perf_counter()
    page = qsvc.load_queue_page(
        page_size=20, after_cursor=cursor, filters=filters,
        doc_conn=_live_conn(_doc_conn), crm_conn=crm_conn,
    )
    page.metrics["render_total_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    st.session_state.qfirst_page_cache = {"sig": sig, "page": page}
    return page


def _render_metrics(page: qsvc.QueuePage) -> None:
    m = page.metrics
    st.caption(
        f"FIRST_QUEUE_QUERY_MS={m['first_queue_query_ms']} · "
        f"CRM_LOOKUP_MS={m['crm_lookup_ms']} · "
        f"DB_QUERIES_BEFORE_FIRST_20_CARDS={m['db_queries']} · "
        f"scanned={m['scanned_rows']} · cards={len(page.cards)} · "
        f"total={m.get('render_total_ms', '?')} ms"
    )


@st.cache_data(ttl=30, show_spinner=False)
def _pipeline_line() -> Dict[str, Any]:
    return pov.load_pipeline_line()


def _snapshot(crm_conn) -> Dict[str, Any]:
    now = time.time()
    cached = st.session_state.get("qfirst_snapshot")
    if cached and now - cached["ts"] < 120:
        return cached["data"]
    data = qsvc.load_queue_snapshot(doc_conn=_live_conn(_doc_conn), crm_conn=crm_conn)
    st.session_state.qfirst_snapshot = {"ts": now, "data": data}
    return data


def _render_snapshot(crm_conn) -> None:
    """Second row: how much is processed now, active cards by medal, open tenders."""
    snap = _snapshot(crm_conn)
    st.caption("Сводка производства (кеш 2 мин, дешёвые агрегаты)")
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Обработано", snap["processed"])
    a2.metric("В работе / ожидает", snap["waiting"] + snap["processing"])
    a3.metric("Ошибка / нет ссылок", snap["errors"])
    a4.metric("Всего в очереди", snap["queue_total"])

    medals = snap["medals"]
    b1, b2, b3, b4, b5, b6, b7 = st.columns(7)
    b1.metric("Активных карт", snap["active_cards"])
    b2.metric("🥇 GOLD", medals.get("GOLD", 0))
    b3.metric("🥈 SILVER", medals.get("SILVER", 0))
    b4.metric("🥉 BRONZE", medals.get("BRONZE", 0))
    b5.metric("🪵 WOOD", medals.get("WOOD", 0))
    b6.metric("Идут торги (OPEN)", snap["open"])
    b7.metric("Разыграно (AWARDED)", snap["awarded"])
    st.divider()


def _render_pagination(page: qsvc.QueuePage) -> None:
    left, mid, right = st.columns([1, 2, 1])
    stack = st.session_state.get("qfirst_cursor_stack", [])
    with left:
        if st.button("← Назад", disabled=not stack, use_container_width=True, key="qfirst_prev"):
            st.session_state.qfirst_start_cursor = stack.pop()
            st.session_state.qfirst_cursor_stack = stack
            st.session_state.pop("qfirst_page_cache", None)
            st.rerun()
    with right:
        if st.button(
            "Вперёд →",
            disabled=not page.next_cursor,
            use_container_width=True,
            key="qfirst_next",
        ):
            cur = st.session_state.get("qfirst_start_cursor")
            st.session_state.qfirst_cursor_stack = stack + [cur]
            st.session_state.qfirst_start_cursor = page.next_cursor
            st.session_state.pop("qfirst_page_cache", None)
            st.rerun()


# ── Lazy card detail ────────────────────────────────────────────────────────

def _get_detail(pid: int, crm_conn) -> Dict[str, Any]:
    cache = st.session_state.setdefault("qfirst_detail_cache", {})
    if pid not in cache:
        cache[pid] = qsvc.load_card_detail(pid, crm_conn=crm_conn)
    return cache[pid]


def _render_open_card(card, crm_conn) -> None:
    store = st.session_state
    if st.button("Свернуть", key=f"qfirst_close_{card.procurement_id}"):
        store.qfirst_open_id = None
        st.rerun()
    with st.container(border=True):
        detail = _get_detail(card.procurement_id, crm_conn)
        render_card_detail(card, detail)
        _render_lazy_layers(card, crm_conn)


def _render_lazy_layers(card, crm_conn) -> None:
    pid = card.procurement_id
    c1, c2 = st.columns(2)
    with c1:
        if st.button("📄 Документы", key=f"qfirst_docs_btn_{pid}"):
            st.session_state.qfirst_load_docs = pid
    with c2:
        if st.button("🤖 AI / история", key=f"qfirst_ai_btn_{pid}"):
            st.session_state.qfirst_load_ai = pid

    if st.session_state.get("qfirst_load_docs") == pid:
        _render_documents_layer(pid)
    if st.session_state.get("qfirst_load_ai") == pid:
        _render_ai_layer(pid, crm_conn)


def _render_documents_layer(pid: int) -> None:
    st.markdown("**Документы (загружено по клику):**")
    try:
        from src.services.commercial_routing_v3.research_ui_projection import (
            load_research_ui_projection,
        )
        projection = load_research_ui_projection([pid], None).get(pid)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось загрузить документы: {type(exc).__name__}")
        return
    if projection is None:
        st.info("Документальный слой недоступен.")
        return
    a, b, c = st.columns(3)
    a.metric("Документов", projection.documents_total)
    b.metric("Обработано", projection.documents_researched)
    c.metric("С evidence", projection.documents_with_evidence)
    st.caption(
        f"research_state={projection.research_state} · "
        f"категории: {', '.join(projection.category_names or projection.category_codes or []) or '—'}"
    )


def _render_ai_layer(pid: int, crm_conn) -> None:
    st.markdown("**AI / история (загружено по клику):**")
    data = qsvc.load_card_ai_history(pid, crm_conn=crm_conn)
    assessment = data.get("assessment") or {}
    if assessment:
        st.markdown(
            f"- AI уровень: **{assessment.get('proposed_level') or '—'}** "
            f"(confidence {assessment.get('confidence') or '—'}, "
            f"status {assessment.get('status') or '—'}, stale={assessment.get('is_stale')})\n"
            f"- Object: `{assessment.get('proposed_object_type') or '—'}` · "
            f"Procurement: `{assessment.get('proposed_procurement_type') or '—'}` · "
            f"Route: `{assessment.get('proposed_route_profile') or '—'}`\n"
            f"- Reasons: {str(assessment.get('reasons') or '—')[:400]}"
        )
    else:
        st.caption("AI-оценка для этой закупки не найдена.")
    history = data.get("history") or []
    if history:
        st.markdown("**История ручных правок:**")
        for h in history:
            st.markdown(
                f"- {h.get('timestamp')} · {h.get('user_name') or '—'} "
                f"({h.get('action_type') or '—'}): {h.get('comment') or 'без комментария'}"
            )
    else:
        st.caption("История ручных правок пуста.")


# ── Heavy analytics behind an explicit open ─────────────────────────────────

def _render_analytics_gate() -> None:
    if not st.toggle("📊 Статистика / аналитика", key="qfirst_show_analytics"):
        return
    try:
        from src.ui.analytics_contour_v2_page import _STICKY_CSS

        st.markdown(_STICKY_CSS, unsafe_allow_html=True)
        from src.ui.components.analytics_v2.command_center import render_command_center
        from src.ui.components.analytics_v2.control_room import render_control_room
        from src.ui.components.analytics_v2.header import render_header
        from src.ui.components.analytics_v2.quick_filters import render_quick_filters
        from src.ui.components.analytics_v2.tabs_lazy_dispatch import render_tabs
        from src.ui.analytics_contour_v2_page import _render_filters as legacy_filters

        render_header()
        render_command_center()
        st.divider()
        left, right = st.columns([1, 3], gap="medium")
        with left:
            legacy_filters()
        with right:
            render_quick_filters()
            render_tabs()
        st.divider()
        with st.expander("Техническая информация", expanded=False):
            render_control_room()
    except Exception as exc:  # noqa: BLE001
        st.error(
            "Раздел «Статистика / аналитика» недоступен в этой среде: "
            f"{type(exc).__name__}: {exc}"
        )
