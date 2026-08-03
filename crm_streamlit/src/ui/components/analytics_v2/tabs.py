"""Вкладки для аналитического контура v2."""
from __future__ import annotations

import streamlit as st

from src.ui.components.analytics_v2.card_feed import render_card_feed


def render_tabs() -> None:
    """Рисуем вкладки и ленту карточек в первой вкладке."""
    tabs = st.tabs(["Новые карточки", "Мой портфель", "Обновления", "Компании"])
    with tabs[0]:
        render_card_feed()
    with tabs[1]:
        st.info("Раздел будет подключён на следующем этапе")
    with tabs[2]:
        st.info("Раздел будет подключён на следующем этапе")
    with tabs[3]:
        st.info("Раздел будет подключён на следующем этапе")
