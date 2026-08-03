"""Лимит карточек для аналитического контура v2."""
from __future__ import annotations

import streamlit as st

from src.ui.components.analytics_v2.mock_data import LIMITS


def render_limits() -> None:
    """Открыто: 17 из 25 · 68% · Обновления ранее открытых: бесплатно."""
    opened = LIMITS["opened"]
    limit = LIMITS["limit"]
    pct = int(opened / limit * 100)
    st.caption(
        f"Открыто: **{opened}** из {limit} · {pct}% · Обновления ранее открытых: бесплатно"
    )
