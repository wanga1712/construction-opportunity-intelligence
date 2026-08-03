"""Карточка объекта для аналитического контура v2."""
from __future__ import annotations

import streamlit as st

LEVEL_COLORS = {
    "Gold": "#d4a017",
    "Silver": "#7c8da1",
    "Bronze": "#b36b2c",
    "Wood": "#8c6b4f",
    "Early": "#8c6b4f",
}


def render_object_card(card: dict, index: int) -> None:
    """Рисуем карточку v2 по реальным данным."""
    color = LEVEL_COLORS.get(card.get("level"), "#8c6b4f")
    with st.container(border=True):
        left, right = st.columns([5, 1.2])
        with left:
            st.markdown(
                f"""
                <div style="display:inline-block;padding:2px 10px;border-radius:999px;
                background:{color}22;color:{color};font-size:12px;font-weight:700;">
                {card["level"]}
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.caption(f'{card["object_type"]} · {card["region"]}')
            st.markdown(f'**{card["title"]}**')
            col1, col2, col3 = st.columns(3)
            col1.write(f'Стадия: {card["stage"]}')
            col2.write(f'Подкатегории: {card["category"]}')
            col3.write(f'Обновлено: {card["updated_at"]}')
            col4, col5 = st.columns(2)
            col4.write(f'Найдено: {card["found_summary"]}')
            col5.write(f'Объём: {card["volume"]}')
            st.write(f'Следующий этап: {card["next_step"]}')
            st.write(f'Заказчик: {card["customer"]}')
            st.write(f'Проектировщик: {card["designer"]}')
            st.write(f'Подрядчик: {card["contractor"]}')
            st.caption(f'Причина рейтинга: {card["rating_reason"]}')
        with right:
            st.button("Открыть", key=f"analytics_v2_open_{index}", use_container_width=True)
            st.button("В портфель", key=f"analytics_v2_portfolio_{index}", use_container_width=True)
            st.button("Доказательства", key=f"analytics_v2_proof_{index}", use_container_width=True)
            st.button("Похожие", key=f"analytics_v2_similar_{index}", use_container_width=True)
