"""Страница аналитического контура v2 — статическая структура."""
from __future__ import annotations

import streamlit as st

from src.ui.components.analytics_v2.analytics_expander import render_analytics_expander
from src.ui.components.analytics_v2.header import render_header
from src.ui.components.analytics_v2.kpi_row import render_kpi_row
from src.ui.components.analytics_v2.limits import render_limits
from src.ui.components.analytics_v2.mock_data import CARDS
from src.ui.components.analytics_v2.quick_filters import render_quick_filters
from src.ui.components.analytics_v2.sidebar import render_sidebar
from src.ui.components.analytics_v2.tabs import render_tabs


def render_analytics_contour_v2_page(service) -> None:
    """Рисуем v2 со статической структурой карточек."""
    st.session_state["analytics_v2_cards"] = CARDS
    render_sidebar()
    render_header()
    render_kpi_row()
    render_limits()
    render_quick_filters()
    render_tabs()
    render_analytics_expander()
