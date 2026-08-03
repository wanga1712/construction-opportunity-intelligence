"""Header для аналитического контура v2."""
from __future__ import annotations

import streamlit as st

from src.ui.components.analytics_v2.mock_data import HEADER_OPTIONS


def render_header(options: dict | None = None) -> None:
    """Рисуем верхнюю строку страницы и фильтр подкатегории."""
    options = options or {}
    subcategories = options.get("header_subcategories") or ["Все подкатегории"]
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        st.title("Аналитический контур v2")
        st.caption("Рабочая лента коммерческих объектов")
    with col2:
        st.selectbox("Подкатегория", subcategories, index=0, key="analytics_v2_subcategory")
    with col3:
        st.selectbox("Период", HEADER_OPTIONS["periods"], index=1, key="analytics_v2_period")
