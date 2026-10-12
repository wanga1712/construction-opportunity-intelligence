"""Kanban board layout for the two waterproofing funnels.

Nine stages in one row are unreadable, so the board is split into two bands that
match the business process: the УК funnel (find the company, reach the decision
maker, get access to objects) and the object funnel (survey, proposal,
specification, procurement, contract). Each band is a horizontally scrolling row
of columns.

This module owns layout only. What a card *means* is decided by the caller's card
renderer, so the УК board and the object board share one column contract while
still showing different facts.
"""
from __future__ import annotations

import html
from typing import Any, Callable, Iterable

import streamlit as st

COLUMN_WIDTH = 300
BOARD_HEIGHT = 620
BAND_ACCOUNT = ("Воронка УК", "Найти УК → выйти на ЛПР → провести встречу → получить объекты и доступ")
BAND_DEAL = ("Воронка объектов", "Обследование → техрешение → ТЗ → закупка → контракт по каждому адресу")

CardRenderer = Callable[[dict[str, Any]], None]


def _text(value: Any) -> str:
    """Card text is data, never markup, so it is escaped before it reaches HTML."""
    return html.escape(str(value if value is not None else ""))


def render_band(title: str, subtitle: str) -> None:
    """Header that separates the УК funnel from the object funnel."""
    st.markdown(
        f'<div class="crm-phase"><span class="crm-phase-name">{_text(title)}</span>'
        f'<span class="crm-phase-desc">{_text(subtitle)}</span></div>',
        unsafe_allow_html=True,
    )


def render_column_head(column: dict[str, Any]) -> None:
    """Stage name with its card count, then one line explaining the stage."""
    st.markdown(
        '<div class="crm-board-head">'
        f'<span class="crm-board-name">{_text(column.get("label"))}</span>'
        f'<span class="crm-board-count">{int(column.get("count") or 0)}</span>'
        "</div>"
        f'<div class="crm-board-desc">{_text(column.get("description"))}</div>',
        unsafe_allow_html=True,
    )


def render_column(
    column: dict[str, Any], render_card: CardRenderer, *, width: int = COLUMN_WIDTH
) -> None:
    """One funnel column; both boards reuse this skeleton."""
    with st.container(border=True, width=width):
        render_column_head(column)
        amount = str(column.get("amount_label") or "").strip()
        if amount and amount not in ("—", "0 ₽"):
            st.caption(f"Сумма: {amount}")
        cards = list(column.get("cards") or [])
        if not cards:
            st.caption("— пусто —")
        for card in cards:
            render_card(card)
        hidden = int(column.get("hidden") or 0)
        if hidden:
            st.caption(f"ещё скрыто: {hidden} — уточните фильтр")


def render_kpi_strip(chips: Iterable[dict[str, Any]]) -> None:
    """Compact KPI row: real numbers only, never a demo figure."""
    body = "".join(
        '<div class="crm-chip">'
        f'<span class="crm-chip-ico">{_text(chip.get("icon"))}</span>'
        f'<span class="crm-chip-val">{_text(chip.get("value"))}</span>'
        f'<span class="crm-chip-lbl">{_text(chip.get("label"))}</span>'
        "</div>"
        for chip in chips
    )
    st.markdown(f'<div class="crm-kpi-row">{body}</div>', unsafe_allow_html=True)


def render_board(
    columns: Iterable[dict[str, Any]],
    render_card: CardRenderer,
    *,
    key: str,
    width: int = COLUMN_WIDTH,
    height: int = BOARD_HEIGHT,
) -> None:
    """A horizontally scrolling band of columns.

    A fixed height is what turns on Streamlit's scroll surface, so nine stages
    stay readable instead of being squeezed into the viewport.
    """
    with st.container(horizontal=True, gap="small", height=height, autoscroll=False, key=key):
        for column in columns:
            render_column(column, render_card, width=width)


__all__ = [
    "BAND_ACCOUNT",
    "BAND_DEAL",
    "BOARD_HEIGHT",
    "COLUMN_WIDTH",
    "render_band",
    "render_board",
    "render_column",
    "render_column_head",
    "render_kpi_strip",
]
