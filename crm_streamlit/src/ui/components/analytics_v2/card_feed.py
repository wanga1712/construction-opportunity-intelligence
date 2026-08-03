"""Лента карточек для аналитического контура v2."""
from __future__ import annotations

import streamlit as st

from src.ui.components.analytics_v2.object_card import render_object_card


def render_card_feed() -> None:
    """Рисуем карточки из session_state, а не из моков."""
    cards = st.session_state.get("analytics_v2_cards", [])
    if not cards:
        st.warning("По текущим фильтрам карточки не найдены.")
        return
    for index, card in enumerate(cards, start=1):
        render_object_card(card, index)
