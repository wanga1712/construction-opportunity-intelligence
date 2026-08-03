"""Страница аналитического контура v2 (§14.1–14.3)."""
from __future__ import annotations

import streamlit as st

from src.ui.components.analytics_v2.analytics_expander import render_charts
from src.ui.components.analytics_v2.header import render_header
from src.ui.components.analytics_v2.kpi_row import render_kpi_row
from src.ui.components.analytics_v2.limits import render_limits
from src.ui.components.analytics_v2.mock_data import CARDS
from src.ui.components.analytics_v2.quick_filters import render_quick_filters
from src.ui.components.analytics_v2.tabs import render_tabs


def render_analytics_contour_v2_page(service) -> None:
    """Шапка → KPI → Лимит → Три графика → [Фильтры | Рабочая область]."""
    st.session_state["analytics_v2_cards"] = CARDS

    render_header()
    render_kpi_row()
    render_limits()
    st.divider()
    render_charts()
    st.divider()

    left, right = st.columns([1, 3], gap="medium")

    with left:
        _render_filters()

    with right:
        render_quick_filters()
        render_tabs()


def _render_filters() -> None:
    """Панель фильтров — левая колонка страницы."""
    from src.ui.components.analytics_v2.mock_data import SIDEBAR_OPTIONS

    st.markdown("**ФИЛЬТРЫ**")

    st.selectbox("Профиль", ["Основной профиль", "Светотехника", "Гидроизоляция"], index=0)
    st.selectbox("Категория", ["Светотехника", "Гидроизоляция", "Напольные покрытия", "Все"], index=0)
    st.segmented_control(
        "Уровень",
        ["Все", "Gold", "Silver", "Bronze"],
        default="Все",
        selection_mode="single",
        key="analytics_v2_level_filter",
    )
    st.selectbox("Регион", ["Московская область", "Москва", "Санкт-Петербург", "Все регионы"], index=0)
    st.selectbox("Тип объекта", ["Все", "Социальный", "Инфраструктурный", "Жилой"], index=0)
    st.selectbox("Заказчик", ["Все", "ГКУ Московской области", "ГБУ «УКС»"], index=0)
    st.radio(
        "Показывать",
        ["Все", "Новые", "Обновлённые", "Сохранённые"],
        index=0,
        key="analytics_v2_show_mode",
    )
    st.button("Расширенные фильтры", use_container_width=True)
    st.button("Сбросить фильтры", use_container_width=True)
