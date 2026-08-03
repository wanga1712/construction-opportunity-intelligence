"""Сортировка и режим отображения рабочей области v2."""
from __future__ import annotations

import streamlit as st


def render_quick_filters() -> None:
    """Сортировка и режим над лентой карточек."""
    col1, col2 = st.columns([3, 1])
    with col1:
        st.selectbox(
            "Сортировка",
            ["По приоритету", "По дате обновления", "По стадии"],
            index=0,
            key="analytics_v2_sort",
            label_visibility="collapsed",
        )
    with col2:
        st.segmented_control(
            "Вид",
            ["Карточки", "Таблица"],
            default="Карточки",
            selection_mode="single",
            key="analytics_v2_view_mode",
            label_visibility="collapsed",
        )
