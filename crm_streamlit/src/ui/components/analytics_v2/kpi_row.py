"""KPI-ряд для аналитического контура v2."""
from __future__ import annotations

import streamlit as st

from src.ui.components.analytics_v2.mock_data import KPI_VALUES


def render_kpi_row() -> None:
    """Рисуем семь KPI через st.metric."""
    columns = st.columns(7)
    for column, (label, value) in zip(columns, KPI_VALUES):
        with column:
            st.metric(label, value)
