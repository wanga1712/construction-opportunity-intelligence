"""Лимиты для аналитического контура v2."""
from __future__ import annotations

import streamlit as st

from src.ui.components.analytics_v2.mock_data import LIMITS


def render_limits() -> None:
    """Рисуем компактный блок лимитов."""
    with st.container(border=True):
        st.caption("Лимиты текущего периода")
        columns = st.columns(4)
        for column, item in zip(columns, LIMITS):
            with column:
                st.write(f"{item['label']} {item['used']} / {item['limit']}")
                st.progress(item["used"] / item["limit"])
