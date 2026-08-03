"""Быстрые фильтры для аналитического контура v2."""
from __future__ import annotations

import streamlit as st


def render_quick_filters() -> None:
    """Рисуем горизонтальную строку быстрых фильтров."""
    col1, col2, col3 = st.columns([2, 2, 1.2])
    with col1:
        st.segmented_control(
            "Уровень",
            ["Все уровни", "Gold", "Silver", "Bronze", "Early"],
            default="Все уровни",
            selection_mode="single",
            key="analytics_v2_level",
        )
    with col2:
        st.selectbox(
            "Сортировка",
            ["По приоритету", "По дате обновления", "По стадии"],
            index=0,
            key="analytics_v2_sort",
        )
    with col3:
        st.segmented_control(
            "Режим отображения",
            ["Карточки", "Таблица"],
            default="Карточки",
            selection_mode="single",
            key="analytics_v2_view_mode",
        )
