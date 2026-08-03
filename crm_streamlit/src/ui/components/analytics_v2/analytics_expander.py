"""Три графика аналитического контура v2 — над рабочей областью."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.ui.components.analytics_v2.mock_data import CHARTS


def render_charts() -> None:
    """Объекты по стадиям / Уровни карточек / Категории — одна строка."""
    col1, col2, col3 = st.columns(3)
    with col1:
        st.caption("Объекты по стадиям")
        st.bar_chart(pd.DataFrame(CHARTS["stages"]).set_index("label"))
    with col2:
        st.caption("Уровни карточек")
        st.bar_chart(pd.DataFrame(CHARTS["levels"]).set_index("label"))
    with col3:
        st.caption("Категории")
        st.bar_chart(pd.DataFrame(CHARTS["categories"]).set_index("label"))


# Обратная совместимость — старое имя функции
render_analytics_expander = render_charts
