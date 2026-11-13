"""Procurement object cards for the three-zone commercial market."""
from __future__ import annotations

from typing import Any, Iterable

import streamlit as st


def _state_label(card: dict[str, Any]) -> str:
    state = str(card.get("state") or "")
    if state == "MATCHED":
        return str(card.get("medal") or "MATCHED")
    if state == "ZERO_MATCH":
        return "ZERO MATCH"
    if state == "IN_RESEARCH":
        return "IN RESEARCH"
    return "NO ESTIMATE"


def _foot(card: dict[str, Any]) -> list[str]:
    state = card.get("state")
    if state == "MATCHED":
        return [
            f"{int(card.get('category_count') or 0)} категорий",
            f"{int(card.get('estimate_rows') or 0):,} позиций".replace(",", " "),
            f"{card.get('material_value_text') or '—'} найденных материалов",
        ]
    if state == "ZERO_MATCH":
        return [
            f"Смета: {int(card.get('estimate_rows') or 0):,} строк".replace(",", " "),
            f"Полных позиций: {int(card.get('complete_positions') or 0):,}".replace(",", " "),
            "Совпадений с текущими категориями не найдено",
        ]
    if state == "IN_RESEARCH":
        return [
            f"Документов: {int(card.get('documents') or 0)}",
            f"Статус обработки: {card.get('queue_status') or '—'}",
        ]
    return ["Смета ещё не сформирована"]


def _render_card(card: dict[str, Any], *, selected: bool) -> int | None:
    pid = int(card["procurement_id"])
    title = str(card.get("auction_name") or "Без названия")
    number = str(card.get("contract_number") or "—")
    region = str(card.get("delivery_region") or "Регион не указан")
    deadline = str(card.get("deadline_text") or "—")
    lifecycle = str(card.get("source_lifecycle") or "—")
    state = _state_label(card)

    with st.container(border=True, key=f"market_object_{pid}"):
        state_col, value_col = st.columns([1.2, 1], vertical_alignment="center")
        state_col.markdown(f"**{state}**")
        value_col.markdown(f"**{card.get('nmck_text') or '—'}**  \nНМЦК")
        if st.button(
            title,
            key=f"market_select_{pid}",
            type="primary" if selected else "secondary",
            use_container_width=True,
            help=f"Открыть досье закупки № {number}",
        ):
            return pid
        st.caption(f"№ {number} · {region} · до {deadline} · {lifecycle}")
        foot = _foot(card)
        metrics = st.columns(min(3, len(foot)))
        for metric, label in zip(metrics, foot):
            metric.caption(label)
    return None


def render_market_cards(
    cards: Iterable[dict[str, Any]],
    *,
    selected_pid: int | None = None,
) -> int | None:
    """Render selectable native Streamlit cards; return the chosen procurement."""
    rows = list(cards or ())
    if not rows:
        st.markdown(
            '<div class="crm-list-empty">По текущим фильтрам объектов нет. '
            'Измените категории, состояние или строку поиска.</div>',
            unsafe_allow_html=True,
        )
        return None

    with st.container(height=690, border=False, key="market_card_scroll"):
        for card in rows:
            selected = selected_pid == int(card["procurement_id"])
            chosen = _render_card(card, selected=selected)
            if chosen is not None:
                return chosen
    return None
