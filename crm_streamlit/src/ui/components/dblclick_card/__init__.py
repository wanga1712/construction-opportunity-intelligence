"""Streamlit custom component: список карточек с двойным кликом."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

_COMPONENT_DIR = Path(__file__).resolve().parent

_dblclick_cards = components.declare_component(
    "dblclick_object_cards",
    path=str(_COMPONENT_DIR),
)


def dblclick_cards_batch(
    cards: list[dict[str, Any]],
    *,
    height: int = 600,
    key: str | None = None,
) -> str | None:
    """Показать список HTML-карточек. При двойном клике вернуть key объекта."""
    return _dblclick_cards(
        cards=cards,
        height=height,
        key=key,
        default=None,
    )


def batch_widget_key(tab_key: str, page: int) -> str:
    """Уникальный ключ виджета для страницы списка."""
    gen = st.session_state.get("dcard_gen", 0)
    return f"dcard_batch_{tab_key}_p{page}_{gen}"
