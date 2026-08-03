"""Компактная карточка объекта для аналитического контура v2 (§14.3)."""
from __future__ import annotations

import streamlit as st

LEVEL_COLORS = {
    "Gold": "#d4a017",
    "Silver": "#7c8da1",
    "Bronze": "#b36b2c",
    "Wood": "#8c6b4f",
}


def render_object_card(card: dict, index: int) -> None:
    """Уровень·категория, название, регион, стадия, срок, найдено, объём, участники, дата."""
    color = LEVEL_COLORS.get(card.get("level"), "#8c6b4f")
    with st.container(border=True):
        left, right = st.columns([5, 1])
        with left:
            st.markdown(
                f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
                f'background:{color}22;color:{color};font-size:12px;font-weight:700;">'
                f'{card["level"]} · {card["category"]}</span>',
                unsafe_allow_html=True,
            )
            st.markdown(f'**{card["title"]}**')
            c1, c2, c3, c4 = st.columns(4)
            c1.caption(f'📍 {card["region"]}')
            c2.caption(f'Стадия: {card["stage"]}')
            c3.caption(f'Срок до торгов: {card.get("deadline", "—")}')
            c4.caption(f'Обновлено: {card["updated_at"]}')
            c5, c6 = st.columns(2)
            c5.write(f'Найдено: {card.get("found_summary", "—")}')
            c6.write(f'Объём: {card["volume"]}')
            st.caption(
                f'Заказчик: {card["customer"]} · '
                f'Проектировщик: {card["designer"]} · '
                f'Подрядчик: {card["contractor"]}'
            )
            also = card.get("also_on_object") or []
            if also:
                links = " · ".join(also)
                st.caption(f"Дополнительно на объекте: {links}")
        with right:
            st.button("Открыть карточку", key=f"v2_open_{index}", use_container_width=True)
            st.button("☆", key=f"v2_fav_{index}", use_container_width=True)
            st.button("Похожие", key=f"v2_sim_{index}", use_container_width=True)
