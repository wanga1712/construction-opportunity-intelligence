"""Верхняя панель нового аналитического контура."""
from __future__ import annotations

import streamlit as st


def ensure_header_state() -> None:
    """Инициализация состояния экрана."""
    defaults = {
        "selected_category": "Все категории",
        "selected_period": "30 дней",
        "view_mode": "Карточки",
        "quick_tier": "Все",
        "current_tab": "Новые карточки",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_header(group_labels: list[str]):
    """Заголовок, категория, период и быстрые режимы."""
    ensure_header_state()
    left, right = st.columns([3.2, 1.4])
    with left:
        st.title("Аналитический контур")
        st.caption(
            "Главная / Новые карточки / Портфель / Обновления / Компании / Аналитика"
        )
    with right:
        options = ["Все категории"] + group_labels
        current = st.session_state["selected_category"]
        st.session_state["selected_category"] = st.selectbox(
            "Категория",
            options,
            index=options.index(current) if current in options else 0,
        )

    period_col, view_col, tier_col = st.columns([1.2, 1.4, 1.4])
    with period_col:
        st.session_state["selected_period"] = st.segmented_control(
            "Период",
            ["7 дней", "30 дней", "90 дней"],
            selection_mode="single",
            default=st.session_state["selected_period"],
        )
    with view_col:
        st.session_state["view_mode"] = st.segmented_control(
            "Режим",
            ["Карточки", "Таблица", "Компактно"],
            selection_mode="single",
            default=st.session_state["view_mode"],
        )
    with tier_col:
        st.session_state["quick_tier"] = st.segmented_control(
            "Быстрый фильтр",
            ["Все", "Gold", "Silver", "Bronze", "Early"],
            selection_mode="single",
            default=st.session_state["quick_tier"],
        )

    st.query_params.update(
        {
            "category": st.session_state["selected_category"],
            "period": st.session_state["selected_period"],
            "view": st.session_state["view_mode"],
            "tier": st.session_state["quick_tier"],
        }
    )
