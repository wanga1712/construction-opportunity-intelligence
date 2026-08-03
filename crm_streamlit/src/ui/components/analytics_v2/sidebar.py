"""Sidebar фильтры аналитического контура v2."""
from __future__ import annotations

import streamlit as st

from src.ui.components.analytics_v2.mock_data import SIDEBAR_OPTIONS


def render_sidebar(options: dict | None = None) -> None:
    """Профиль / категория / уровень / регион / тип / заказчик / режим."""
    with st.sidebar:
        st.header("Фильтры")
        st.selectbox("Профиль", ["Светотехника", "Гидроизоляция", "Напольные покрытия"], index=0)
        st.multiselect(
            "Категория",
            SIDEBAR_OPTIONS["categories"],
            default=SIDEBAR_OPTIONS["categories"],
        )
        st.segmented_control(
            "Уровень",
            ["Все", "Gold", "Silver", "Bronze"],
            default="Все",
            selection_mode="single",
            key="analytics_v2_level_sidebar",
        )
        st.multiselect(
            "Регион",
            SIDEBAR_OPTIONS["regions"],
            default=SIDEBAR_OPTIONS["regions"][:2],
        )
        st.selectbox("Тип объекта", ["Все типы", "Социальный", "Инфраструктурный", "Жилой"], index=0)
        st.selectbox("Заказчик", ["Все", "ГКУ Московской области", "ГБУ «УКС»"], index=0)
        st.radio(
            "Показывать",
            ["Все", "Новые", "Обновлённые", "Сохранённые"],
            index=0,
            key="analytics_v2_mode_sidebar",
        )
        st.button("Расширенные фильтры", use_container_width=True)
        st.button("Сбросить фильтры", use_container_width=True)
