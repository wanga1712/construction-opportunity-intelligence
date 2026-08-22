"""РАЗМЕТКА — dedicated expert annotation workbench (bypasses publication gate)."""
from __future__ import annotations

import streamlit as st
from typing import Any, Optional

from src.services.annotation_queue_service import (
    ANNOTATION_FILTER_ALL,
    ANNOTATION_FILTER_ANNOTATED,
    ANNOTATION_FILTER_UNANNOTATED,
    AnnotationQueueFilters,
    MODEL_SOURCE_ALL,
    MODEL_SOURCE_LEGACY,
    MODEL_SOURCE_RAW,
    PUBLICATION_FILTER_ALL,
    PUBLICATION_FILTER_HIDDEN,
    PUBLICATION_FILTER_VISIBLE,
    QUEUE_MODE_ALL_CURRENT,
    QUEUE_MODE_OPEN_ASSESSED,
    batch_publication_visibility,
    fetch_model_category_choices,
    fetch_procurement_header,
    fetch_queue_counters,
    fetch_queue_ids,
    lifecycle_label,
)
from src.services.expert_annotation_service import (
    load_expert_annotation,
    load_model_assessment_for_annotation,
)
from src.ui.components.analytics_v2.annotation_card import render_annotation_card
from src.ui.components.analytics_v2.annotation_queue import bind_and_advance

_SESSION_FILTERS = "annotation_wb_filters"
_SESSION_PAGE = "annotation_wb_page"
_SESSION_PAGE_SIZE = "annotation_wb_page_size"
_SESSION_SELECTED = "annotation_wb_selected_id"
_QUEUE_SESSION_KEY = "annotation_wb_queue"
_BUILD_ID = "CRM-V3-EXPERT-ANNOTATION-MVP-1/count-clarity"
_WIDGET_KEYS = (
    "annotation_wb_queue_mode",
    "annotation_wb_annotation_status",
    "annotation_wb_model_source",
    "annotation_wb_publication_visibility",
    "annotation_wb_model_category",
)


def _filters_from_session() -> AnnotationQueueFilters:
    raw = st.session_state.get(_SESSION_FILTERS) or {}
    return AnnotationQueueFilters(
        queue_mode=raw.get("queue_mode", QUEUE_MODE_OPEN_ASSESSED),
        annotation_status=raw.get("annotation_status", ANNOTATION_FILTER_UNANNOTATED),
        model_source=raw.get("model_source", MODEL_SOURCE_ALL),
        publication_visibility=raw.get("publication_visibility", PUBLICATION_FILTER_ALL),
        model_category=raw.get("model_category", "all"),
    )


def _store_filters(f: AnnotationQueueFilters) -> None:
    st.session_state[_SESSION_FILTERS] = {
        "queue_mode": f.queue_mode,
        "annotation_status": f.annotation_status,
        "model_source": f.model_source,
        "publication_visibility": f.publication_visibility,
        "model_category": f.model_category,
    }


def render_annotation_workbench_page(service: Optional[Any]) -> None:
    st.title("🏷️ РАЗМЕТКА")
    st.caption(
        f"Экспертный контур разметки · build `{_BUILD_ID}` · "
        "обходит publication gate CRM · normal «Идут торги» не изменяется."
    )
    if not service or not getattr(service, "crm_db", None):
        st.error("CRM DB недоступна")
        return
    crm_db = service.crm_db

    counters = fetch_queue_counters(crm_db)
    filters = _render_filters(crm_db)
    _store_filters(filters)

    queue_ids = fetch_queue_ids(crm_db, filters)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Активные закупки с оценкой ИИ", counters.get("open_assessed", 0))
    c2.metric("Не размечено", counters.get("open_assessed_unannotated", 0))
    c3.metric("Размечено", counters.get("open_assessed_annotated", 0))
    c4.metric("Текущий фильтр", len(queue_ids))

    queue_labels = {
        QUEUE_MODE_OPEN_ASSESSED: "Активные с оценкой ИИ",
        QUEUE_MODE_ALL_CURRENT: "Все текущие оценки ИИ",
    }
    annotation_labels = {
        ANNOTATION_FILTER_UNANNOTATED: "Не размечено",
        ANNOTATION_FILTER_ANNOTATED: "Размечено",
        ANNOTATION_FILTER_ALL: "Все",
    }
    source_labels = {
        MODEL_SOURCE_ALL: "Все",
        MODEL_SOURCE_RAW: "RAW доступен",
        MODEL_SOURCE_LEGACY: "Legacy / RAW недоступен",
    }
    publication_labels = {
        PUBLICATION_FILTER_ALL: "Все (gate не применяется)",
        PUBLICATION_FILTER_VISIBLE: "Только видно в CRM",
        PUBLICATION_FILTER_HIDDEN: "Только скрыто gate",
    }
    st.info(
        "**Активные фильтры:** "
        f"{queue_labels[filters.queue_mode]} · "
        f"{annotation_labels[filters.annotation_status]} · "
        f"источник: {source_labels[filters.model_source]} · "
        f"publication: {publication_labels[filters.publication_visibility]} · "
        f"категория: {filters.model_category} · **результат: {len(queue_ids)}**"
    )
    if not queue_ids:
        st.info("Очередь пуста для текущих фильтров.")
        return

    page_size_options = [20, 25, 50]
    page_size = st.selectbox(
        "Размер страницы",
        page_size_options,
        index=page_size_options.index(int(st.session_state.get(_SESSION_PAGE_SIZE, 25))),
        key="annotation_wb_page_size_select",
    )
    st.session_state[_SESSION_PAGE_SIZE] = page_size

    all_cards = [{"id": pid} for pid in queue_ids]
    all_cards = bind_and_advance(all_cards, _QUEUE_SESSION_KEY, st.session_state)
    current_id = all_cards[0]["id"]
    pos = queue_ids.index(current_id)
    page = pos // page_size + 1
    st.session_state[_SESSION_PAGE] = page
    total_pages = max(1, (len(queue_ids) + page_size - 1) // page_size)
    start = (page - 1) * page_size
    page_ids = queue_ids[start : start + page_size]

    nav1, nav2, nav3 = st.columns([1, 2, 1])
    if nav1.button("← Предыдущая страница", disabled=page <= 1, key="ann_wb_prev_page"):
        st.session_state[_SESSION_PAGE] = page - 1
        st.session_state[_QUEUE_SESSION_KEY] = queue_ids[(page - 2) * page_size]
        st.rerun()
    nav2.caption(
        f"Страница {page}/{total_pages} · в очереди {len(queue_ids)} · "
        f"позиция {pos + 1}"
    )
    if nav3.button("Следующая страница →", disabled=page >= total_pages, key="ann_wb_next_page"):
        st.session_state[_SESSION_PAGE] = page + 1
        st.session_state[_QUEUE_SESSION_KEY] = queue_ids[page * page_size]
        st.rerun()

    st.markdown(f"**Карточка {pos + 1}/{len(queue_ids)}** · procurement_id=`{current_id}`")

    header = fetch_procurement_header(crm_db, current_id)
    if not header:
        st.error("Закупка не найдена")
        return
    assessment = load_model_assessment_for_annotation(current_id, crm_db)
    existing = load_expert_annotation(current_id, crm_db)
    pub_vis = batch_publication_visibility(crm_db, [current_id]).get(current_id, False)
    lc = lifecycle_label(header)

    if existing:
        st.info(
            f"📝 Разметка v{existing.get('annotation_version')} · "
            f"автор: {existing.get('created_by') or '—'}"
        )

    render_annotation_card(
        crm_db=crm_db,
        procurement_id=current_id,
        header=header,
        assessment=assessment,
        existing_annotation=existing,
        publication_visible=pub_vis,
        lifecycle_label=lc,
    )


def _render_filters(crm_db: Any) -> AnnotationQueueFilters:
    prev = _filters_from_session()
    if st.button("Сбросить фильтры разметки", key="annotation_wb_reset_filters"):
        for key in (
            _SESSION_FILTERS,
            _SESSION_PAGE,
            _SESSION_SELECTED,
            _QUEUE_SESSION_KEY,
            *_WIDGET_KEYS,
        ):
            st.session_state.pop(key, None)
        st.rerun()

    f1, f2, f3, f4, f5 = st.columns(5)

    queue_opts = {
        QUEUE_MODE_OPEN_ASSESSED: "Активные с оценкой ИИ",
        QUEUE_MODE_ALL_CURRENT: "Все текущие оценки ИИ",
    }
    ann_opts = {
        ANNOTATION_FILTER_UNANNOTATED: "Не размечено",
        ANNOTATION_FILTER_ANNOTATED: "Размечено",
        ANNOTATION_FILTER_ALL: "Все",
    }
    src_opts = {
        MODEL_SOURCE_ALL: "Все",
        MODEL_SOURCE_RAW: "RAW доступен",
        MODEL_SOURCE_LEGACY: "Legacy / RAW недоступен",
    }
    pub_opts = {
        PUBLICATION_FILTER_ALL: "Все",
        PUBLICATION_FILTER_VISIBLE: "Видно в CRM",
        PUBLICATION_FILTER_HIDDEN: "Скрыто publication gate",
    }

    q_key = f1.selectbox(
        "LIFECYCLE QUEUE",
        list(queue_opts.keys()),
        format_func=lambda k: queue_opts[k],
        index=list(queue_opts.keys()).index(prev.queue_mode),
        key=_WIDGET_KEYS[0],
    )
    a_key = f2.selectbox(
        "ANNOTATION STATUS",
        list(ann_opts.keys()),
        format_func=lambda k: ann_opts[k],
        index=list(ann_opts.keys()).index(prev.annotation_status),
        key=_WIDGET_KEYS[1],
    )
    s_key = f3.selectbox(
        "MODEL SOURCE",
        list(src_opts.keys()),
        format_func=lambda k: src_opts[k],
        index=list(src_opts.keys()).index(prev.model_source),
        key=_WIDGET_KEYS[2],
    )
    p_key = f4.selectbox(
        "PUBLICATION VISIBILITY",
        list(pub_opts.keys()),
        format_func=lambda k: pub_opts[k],
        index=list(pub_opts.keys()).index(prev.publication_visibility),
        key=_WIDGET_KEYS[3],
    )

    cat_choices = ["all"] + fetch_model_category_choices(crm_db)
    cat_key = f5.selectbox(
        "MODEL CATEGORY",
        cat_choices,
        index=cat_choices.index(prev.model_category) if prev.model_category in cat_choices else 0,
        key=_WIDGET_KEYS[4],
    )

    return AnnotationQueueFilters(
        queue_mode=q_key,
        annotation_status=a_key,
        model_source=s_key,
        publication_visibility=p_key,
        model_category=cat_key,
    )
