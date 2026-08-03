"""Sidebar для аналитического контура v2."""
from __future__ import annotations

import streamlit as st

from src.ui.components.analytics_v2.mock_data import SIDEBAR_OPTIONS


def render_sidebar(options: dict | None = None) -> None:
    """Рисуем фильтры и настройки с динамическими подкатегориями из БД."""
    options = options or {}
    subcategories = options.get("sidebar_subcategories") or []
    with st.sidebar:
        st.header("Фильтры и настройки")
        st.multiselect("Подкатегории", subcategories, default=subcategories, key="analytics_v2_sidebar_subcategories")
        st.multiselect("Регионы", SIDEBAR_OPTIONS["regions"], default=SIDEBAR_OPTIONS["regions"][:2])
        st.multiselect("Стадии", SIDEBAR_OPTIONS["stages"], default=SIDEBAR_OPTIONS["stages"])
        st.multiselect("Уровни", SIDEBAR_OPTIONS["levels"], default=SIDEBAR_OPTIONS["levels"])
        st.checkbox("Только с документами", value=True)
        st.checkbox("Только с объёмом")
        st.checkbox("Только с подрядчиком")
        st.selectbox("Дата обновления", SIDEBAR_OPTIONS["updated_ranges"], index=2)
        st.button("Сбросить фильтры", use_container_width=True)
