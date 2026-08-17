"""Новая экспериментальная страница аналитического контура."""
from __future__ import annotations

import math

import streamlit as st

from src.services.analytics_contour_service import (
    AnalyticsContourService,
    cached_reference_data,
    get_analytics_contour_repository,
)
from src.ui.components.analytics_charts import render_charts
from src.ui.components.object_card import render_object_cards
from src.ui.components.object_detail import render_object_detail
from src.ui.session_deps import get_objects_service

PAGE_SIZES = [10, 15, 20]
TAB_KEYS = {
    "Новые карточки": "copy_new_page",
    "Мой портфель": "copy_portfolio_page",
    "Обновления": "copy_updates_page",
}


def _ensure_state() -> None:
    """Инициализируем состояние новой страницы."""
    defaults = {
        "copy_selected_category": "Все категории",
        "copy_selected_period": "30 дней",
        "copy_quick_tier": "Все уровни",
        "copy_sort_mode": "По приоритету",
        "copy_view_mode": "Карточки",
        "copy_page_size": 10,
        "copy_search": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    for page_key in TAB_KEYS.values():
        if page_key not in st.session_state:
            st.session_state[page_key] = 1


def _build_filters_panel(service: AnalyticsContourService, group_map, stage_map, tier_map) -> dict:
    """Строим левую колонку фильтров внутри страницы."""
    region_options = service.regions()
    region_names = [name for _, name in region_options]
    region_map = {name: rid for rid, name in region_options}

    with st.container(border=True):
        st.markdown("### Фильтры и настройки")
        search = st.text_input("Поиск объекта", value=st.session_state["copy_search"])
        selected_regions = st.multiselect("Регион", region_names, default=region_names)
        selected_groups = st.multiselect("Категория", list(group_map.values()), default=list(group_map.values()))
        selected_tiers = st.multiselect("Уровень", list(tier_map.values()), default=list(tier_map.values()))
        selected_stages = st.multiselect("Стадия", list(stage_map.values()), default=list(stage_map.values()))
        only_docs = st.checkbox("Только с документами")
        only_volume = st.checkbox("Только с объёмом")
        only_contractor = st.checkbox("Только с подрядчиком")

    st.session_state["copy_search"] = search
    return {
        "search": search,
        "region_ids": {region_map[name] for name in selected_regions if name in region_map},
        "group_codes": {code for code, label in group_map.items() if label in selected_groups} or set(group_map.keys()),
        "tier_codes": {code for code, label in tier_map.items() if label in selected_tiers} or set(tier_map.keys()),
        "stage_codes": {code for code, label in stage_map.items() if label in selected_stages} or set(stage_map.keys()),
        "only_docs": only_docs,
        "only_volume": only_volume,
        "only_contractor": only_contractor,
    }


def _compact_kpi_row(kpi: dict[str, int], limits_connected: bool) -> None:
    """Рисуем компактную строку KPI."""
    cols = st.columns(7)
    for col, (label, value) in zip(cols, kpi.items()):
        with col:
            st.caption(label)
            st.markdown(f"### {int(value)}")
    st.caption("Лимиты подключены" if limits_connected else "Лимиты не подключены")


def _quick_controls(group_map: dict[str, str]) -> None:
    """Рисуем компактные быстрые фильтры справа."""
    header_left, header_right = st.columns([2.2, 1.4])
    with header_left:
        st.session_state["copy_selected_category"] = st.selectbox(
            "Категория",
            ["Все категории"] + list(group_map.values()),
            index=(["Все категории"] + list(group_map.values())).index(st.session_state["copy_selected_category"]),
            key="copy_category_select",
        )
    with header_right:
        st.session_state["copy_selected_period"] = st.selectbox(
            "Период",
            ["7 дней", "30 дней", "90 дней"],
            index=["7 дней", "30 дней", "90 дней"].index(st.session_state["copy_selected_period"]),
            key="copy_period_select",
        )

    controls_left, controls_mid, controls_right = st.columns([2.3, 1.8, 1.4])
    with controls_left:
        st.session_state["copy_quick_tier"] = st.segmented_control(
            "Уровень",
            ["Все уровни", "Gold", "Silver", "Bronze", "Early"],
            default=st.session_state["copy_quick_tier"],
            selection_mode="single",
            key="copy_quick_tier_control",
        )
    with controls_mid:
        st.session_state["copy_sort_mode"] = st.selectbox(
            "Сортировка",
            ["По приоритету", "По дате обновления", "По стадии"],
            index=["По приоритету", "По дате обновления", "По стадии"].index(st.session_state["copy_sort_mode"]),
            key="copy_sort_select",
        )
    with controls_right:
        st.session_state["copy_view_mode"] = st.segmented_control(
            "Режим",
            ["Карточки", "Таблица"],
            default=st.session_state["copy_view_mode"],
            selection_mode="single",
            key="copy_view_mode_control",
        )


def _sort_items(items: list) -> list:
    """Сортируем список карточек."""
    mode = st.session_state["copy_sort_mode"]
    if mode == "По дате обновления":
        return sorted(items, key=lambda item: str(item.updated_at or item.end_date or ""), reverse=True)
    if mode == "По стадии":
        return sorted(items, key=lambda item: str(item.pipeline_stage_label or ""))
    return sorted(items, key=lambda item: (-(item.ai_priority_score or 0), item.name or ""))


def _paginate(items: list, page_key: str) -> tuple[list, int, int]:
    """Пагинируем карточки."""
    page_size = int(st.session_state["copy_page_size"])
    total_pages = max(1, math.ceil(len(items) / page_size)) if items else 1
    current_page = min(max(int(st.session_state.get(page_key, 1)), 1), total_pages)
    st.session_state[page_key] = current_page
    start = (current_page - 1) * page_size
    return items[start : start + page_size], current_page, total_pages


def _render_pagination(page_key: str, current_page: int, total_pages: int, total_items: int) -> None:
    """Рисуем навигацию по страницам."""
    left, mid, right = st.columns([1, 2, 1])
    with left:
        if st.button("← Назад", key=f"{page_key}_prev", disabled=current_page <= 1, use_container_width=True):
            st.session_state[page_key] = current_page - 1
            st.rerun()
    with mid:
        st.caption(f"Страница {current_page} из {total_pages} · всего карточек: {total_items}")
    with right:
        if st.button("Вперёд →", key=f"{page_key}_next", disabled=current_page >= total_pages, use_container_width=True):
            st.session_state[page_key] = current_page + 1
            st.rerun()


def _render_tab_content(items: list, group_map: dict[str, str], page_key: str, contour_service: AnalyticsContourService) -> None:
    """Рисуем содержимое вкладки."""
    page_items, current_page, total_pages = _paginate(items, page_key)
    if st.session_state["copy_view_mode"] == "Таблица":
        st.dataframe(contour_service.table_view(page_items, group_map), use_container_width=True, hide_index=True)
        _render_pagination(page_key, current_page, total_pages, len(items))
        return
    render_object_cards(page_items, group_map, st.session_state["copy_selected_category"], key_prefix=page_key)
    _render_pagination(page_key, current_page, total_pages, len(items))


def render_analytics_contour_copy_page(service) -> None:
    """Новая страница-копия аналитического контура."""
    _ensure_state()
    repository = get_analytics_contour_repository(get_objects_service(service))
    contour_service = AnalyticsContourService(repository)

    with st.spinner("Загрузка аналитического контура (копия)..."):
        if not contour_service.load(search_query=st.session_state["copy_search"]):
            st.error(repository.objects_service.last_error or "Не удалось загрузить страницу-копию")
            return

    groups = contour_service.groups()
    group_map, source_options, stage_map, tier_map = cached_reference_data(tuple(groups))

    selected_object_id = st.session_state.get("selected_object_id")
    if selected_object_id:
        item = contour_service.get_item(selected_object_id)
        if item:
            render_object_detail(item, group_map)
            return

    st.title("Аналитический контур — копия")
    st.caption("Новая отдельная структура страницы для сборки рабочего кабинета менеджера")

    left, right = st.columns([1.05, 2.95], gap="large")
    with left:
        filters = _build_filters_panel(contour_service, group_map, stage_map, tier_map)
    with right:
        selected_sources = {code for code, _ in source_options}
        quick_tier_map = {
            "Все уровни": "Все",
            "Gold": "gold",
            "Silver": "silver",
            "Bronze": "bronze",
            "Early": "early",
        }
        _quick_controls(group_map)
        items = contour_service.apply_filters(
            search=filters["search"],
            region_ids=filters["region_ids"],
            period_label=st.session_state["copy_selected_period"],
            selected_sources=selected_sources,
            selected_stages=filters["stage_codes"],
            selected_tiers=filters["tier_codes"],
            selected_groups=filters["group_codes"],
            selected_quick_tier=quick_tier_map[st.session_state["copy_quick_tier"]],
            only_docs=filters["only_docs"],
            only_volume=filters["only_volume"],
            only_contractor=filters["only_contractor"],
        )
        items = _sort_items(items)

        kpi = contour_service.kpi(items)
        _compact_kpi_row(kpi, limits_connected=False)
        st.session_state["copy_page_size"] = st.selectbox(
            "Карточек на странице",
            PAGE_SIZES,
            index=PAGE_SIZES.index(int(st.session_state["copy_page_size"])),
            key="copy_page_size_select",
        )

        opened_keys = set(st.session_state.get("opened_cards", []))
        new_items = [item for item in items if (item.pipeline_stage_code or "news_signal") in {"news_signal", "project_design_ai"}]
        portfolio_items = [item for item in items if item.key in opened_keys]
        update_items = [item for item in items if (item.doc_matches or 0) > 0 or (item.ai_priority_score or 0) >= 55]

        tabs = st.tabs(["Новые карточки", "Мой портфель", "Обновления"])
        with tabs[0]:
            _render_tab_content(new_items, group_map, TAB_KEYS["Новые карточки"], contour_service)
        with tabs[1]:
            _render_tab_content(portfolio_items, group_map, TAB_KEYS["Мой портфель"], contour_service)
        with tabs[2]:
            _render_tab_content(update_items, group_map, TAB_KEYS["Обновления"], contour_service)

        with st.expander("Аналитика по текущей выборке", expanded=False):
            render_charts(
                contour_service.stage_chart(items),
                contour_service.tier_chart(items),
                contour_service.category_chart(items, groups),
            )
