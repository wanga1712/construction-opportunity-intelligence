"""Живой аналитический контур с карточками и встроенными фильтрами."""
from __future__ import annotations

import math
from datetime import date
from typing import Iterable

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
SORT_OPTIONS = ["По приоритету", "По дате обновления", "По стадии"]
TABS = ["Новые карточки", "Мой портфель", "Обновления"]


def _latest_label(item) -> str:
    """Возвращаем наиболее полезную дату для списка."""
    for field in ("updated_at", "delivery_end_date", "delivery_start_date", "end_date", "start_date"):
        value = getattr(item, field, None)
        if value:
            return str(value)[:10]
    return "Не найдено в БД"


def _ensure_state() -> None:
    """Инициализируем состояние страницы один раз."""
    defaults = {
        "selected_object_id": None,
        "opened_cards": [],
        "selected_period": "30 дней",
        "sort_mode": SORT_OPTIONS[0],
        "page_size": PAGE_SIZES[0],
        "new_cards_page": 1,
        "portfolio_page": 1,
        "updates_page": 1,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _sync_selected_object() -> None:
    """Подхватываем прямой переход по object_id."""
    object_id = st.query_params.get("object_id")
    if object_id:
        st.session_state["selected_object_id"] = object_id


def _compact_kpi(label: str, value: int) -> None:
    """Компактная KPI-плашка без тяжёлых плиток."""
    st.markdown(
        f"""
        <div style="padding:8px 10px;border:1px solid rgba(49,51,63,.14);
                    border-radius:12px;background:#ffffff;">
          <div style="font-size:12px;color:#667085;">{label}</div>
          <div style="font-size:24px;font-weight:700;line-height:1.1;">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_header(kpi: dict[str, int]) -> None:
    """Рисуем верхний блок страницы."""
    title_col, period_col, page_col = st.columns([4, 1.4, 1.0], vertical_alignment="bottom")
    with title_col:
        st.title("Аналитический контур")
        st.caption("Рабочая лента коммерческих карточек по стадиям и товарным категориям")
    with period_col:
        st.session_state["selected_period"] = st.selectbox(
            "Период",
            ["7 дней", "30 дней", "90 дней"],
            index=["7 дней", "30 дней", "90 дней"].index(st.session_state["selected_period"]),
        )
    with page_col:
        st.session_state["page_size"] = st.selectbox(
            "На странице",
            PAGE_SIZES,
            index=PAGE_SIZES.index(int(st.session_state["page_size"])),
        )

    kpi_cols = st.columns(len(kpi))
    for col, (label, value) in zip(kpi_cols, kpi.items()):
        with col:
            _compact_kpi(label, int(value))

    st.caption("Лимиты не подключены")


def _render_filters(service: AnalyticsContourService, group_map: dict[str, str], stage_map: dict[str, str], tier_map: dict[str, str]) -> dict:
    """Рисуем левую колонку с настройками внутри страницы."""
    region_options = service.regions()
    region_names = [name for _, name in region_options]
    region_map = {name: rid for rid, name in region_options}

    with st.container(border=True):
        st.subheader("Фильтры и настройки")
        selected_groups = st.multiselect(
            "Категория",
            list(group_map.values()),
            default=list(group_map.values()),
        )
        selected_tiers = st.multiselect(
            "Уровень",
            list(tier_map.values()),
            default=list(tier_map.values()),
        )
        selected_stages = st.multiselect(
            "Стадия",
            list(stage_map.values()),
            default=list(stage_map.values()),
        )
        selected_regions = st.multiselect(
            "Регион",
            region_names,
            default=region_names,
        )
        only_volume = st.checkbox("Только с объёмом")
        only_docs = st.checkbox("Только с документами", value=True)
        only_contractor = st.checkbox("Только с подрядчиком")

    return {
        "region_ids": {region_map[name] for name in selected_regions if name in region_map},
        "stage_codes": {code for code, label in stage_map.items() if label in selected_stages} or set(stage_map),
        "tier_codes": {code for code, label in tier_map.items() if label in selected_tiers} or set(tier_map),
        "group_codes": {code for code, label in group_map.items() if label in selected_groups} or set(group_map),
        "only_volume": only_volume,
        "only_docs": only_docs,
        "only_contractor": only_contractor,
    }


def _sort_items(items: list, mode: str) -> list:
    """Сортируем ленту без обращения к несуществующим полям."""
    if mode == "По дате обновления":
        return sorted(items, key=_latest_label, reverse=True)
    if mode == "По стадии":
        return sorted(items, key=lambda item: str(item.pipeline_stage_label or ""))
    return sorted(items, key=lambda item: (-(item.ai_priority_score or 0), item.name or ""))


def _paginate(items: list, page_key: str) -> tuple[list, int, int]:
    """Пагинация списка карточек."""
    page_size = int(st.session_state["page_size"])
    total_pages = max(1, math.ceil(len(items) / page_size)) if items else 1
    current_page = min(max(int(st.session_state.get(page_key, 1)), 1), total_pages)
    start = (current_page - 1) * page_size
    end = start + page_size
    st.session_state[page_key] = current_page
    return items[start:end], current_page, total_pages


def _render_pagination(page_key: str, current_page: int, total_pages: int, total_items: int) -> None:
    """Нижняя навигация списка."""
    left, mid, right = st.columns([1, 2, 1])
    with left:
        if st.button("← Назад", key=f"prev_{page_key}", disabled=current_page <= 1, use_container_width=True):
            st.session_state[page_key] = current_page - 1
            st.rerun()
    with mid:
        st.caption(f"Страница {current_page} из {total_pages} · карточек: {total_items}")
    with right:
        if st.button("Вперёд →", key=f"next_{page_key}", disabled=current_page >= total_pages, use_container_width=True):
            st.session_state[page_key] = current_page + 1
            st.rerun()


def _render_feed(items: list, page_key: str, group_map: dict[str, str], contour_service: AnalyticsContourService) -> None:
    """Показываем карточки или таблицу внутри выбранной вкладки."""
    page_items, current_page, total_pages = _paginate(items, page_key)
    view_mode = st.segmented_control(
        "Режим",
        ["Карточки", "Таблица"],
        default="Карточки",
        selection_mode="single",
        key=f"view_mode_{page_key}",
    )
    if view_mode == "Таблица":
        st.dataframe(contour_service.table_view(page_items, group_map), use_container_width=True, hide_index=True)
        _render_pagination(page_key, current_page, total_pages, len(items))
        return

    render_object_cards(page_items, group_map, key_prefix=page_key)
    _render_pagination(page_key, current_page, total_pages, len(items))


def _render_right_panel(items: list, contour_service: AnalyticsContourService, group_map: dict[str, str], stage_map: dict[str, str], groups: list[tuple[str, str]]) -> None:
    """Правая часть: сортировка, вкладки, карточки и аналитика."""
    selected_object_id = st.session_state.get("selected_object_id")
    if selected_object_id:
        item = contour_service.get_item(selected_object_id)
        if item:
            render_object_detail(item, group_map)
            return

    sort_col, date_col = st.columns([1.3, 1.2], vertical_alignment="bottom")
    with sort_col:
        st.session_state["sort_mode"] = st.selectbox(
            "Сортировка",
            SORT_OPTIONS,
            index=SORT_OPTIONS.index(st.session_state["sort_mode"]),
        )
    with date_col:
        st.caption(f"Обновлено по выборке: {date.today().isoformat()}")

    sorted_items = _sort_items(items, st.session_state["sort_mode"])
    opened_keys = set(st.session_state.get("opened_cards", []))
    new_codes = {"news_signal", "project_design_ai", "positive_expertise"}
    update_items = [item for item in sorted_items if (item.doc_matches or 0) > 0 or (item.ai_priority_score or 0) >= 55]
    tab_items = {
        "Новые карточки": [item for item in sorted_items if (item.pipeline_stage_code or "news_signal") in new_codes],
        "Мой портфель": [item for item in sorted_items if item.key in opened_keys],
        "Обновления": update_items,
    }

    tabs = st.tabs(TABS)
    page_keys = {"Новые карточки": "new_cards_page", "Мой портфель": "portfolio_page", "Обновления": "updates_page"}
    for tab, label in zip(tabs, TABS):
        with tab:
            _render_feed(tab_items[label], page_keys[label], group_map, contour_service)

    with st.expander("Аналитика по текущей выборке", expanded=False):
        render_charts(
            contour_service.stage_chart(sorted_items),
            contour_service.tier_chart(sorted_items),
            contour_service.category_chart(sorted_items, groups),
        )
        st.caption(f"Стадий в справочнике: {len(stage_map)}")


def render_analytics_contour_page(service) -> None:
    """Главная страница аналитического контура."""
    _ensure_state()
    _sync_selected_object()

    repository = get_analytics_contour_repository(get_objects_service(service))
    contour_service = AnalyticsContourService(repository)

    with st.spinner("Загрузка аналитического контура..."):
        if not contour_service.load(search_query=st.query_params.get("search", "")):
            st.error(repository.objects_service.last_error or "Не удалось загрузить аналитический контур")
            return

    groups = contour_service.groups()
    group_map, source_options, stage_map, tier_map = cached_reference_data(tuple(groups))
    filtered_items = contour_service.items()

    kpi_raw = contour_service.kpi(filtered_items, set(st.session_state.get("opened_cards", [])))
    kpi = dict(kpi_raw) if isinstance(kpi_raw, list) else kpi_raw
    _render_header(kpi)
    page_left, page_right = st.columns([1.05, 2.55], gap="large")

    with page_left:
        filters = _render_filters(contour_service, group_map, stage_map, tier_map)

    selected_sources = {code for code, _ in source_options}
    filtered_items = contour_service.apply_filters(
        search="",
        region_ids=filters["region_ids"],
        period_label=st.session_state["selected_period"],
        selected_sources=selected_sources,
        selected_stages=filters["stage_codes"],
        selected_tiers=filters["tier_codes"],
        selected_groups=filters["group_codes"],
        selected_quick_tier="Все",
        only_docs=filters["only_docs"],
        only_volume=filters["only_volume"],
        only_contractor=filters["only_contractor"],
    )

    with page_right:
        _render_right_panel(filtered_items, contour_service, group_map, stage_map, groups)
