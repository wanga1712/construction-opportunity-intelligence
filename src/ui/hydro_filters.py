"""Compact filter toolbar for the waterproofing boards.

One row, not a panel: search, district, manager, status, overdue and active-only,
plus a reset. Every option is built from the cards that actually exist, so the
toolbar can never offer a choice that matches nothing.
"""
from __future__ import annotations

from typing import Any, Iterable

import streamlit as st

from src.services.waterproofing_funnel import (
    FUNNEL_ACCOUNT,
    FUNNEL_DEAL,
    STAGE_LABELS,
    funnel_stages,
)

ANY_STAGE = ""
ALL_DISTRICTS = "Все районы"
ALL_MANAGERS = "Все менеджеры"


def _filter_keys(prefix: str) -> tuple[str, ...]:
    return tuple(
        f"{prefix}_{name}"
        for name in ("query", "district", "responsible", "stage", "overdue", "active")
    )


def reset_filters(prefix: str = "hydro_filter") -> None:
    """Clear every toolbar widget and rebuild the board from scratch."""
    for key in _filter_keys(prefix):
        st.session_state.pop(key, None)


def stage_options() -> list[str]:
    """Every stage id of both funnels, in board order.

    Ids stay unique across the two funnels, so one status filter can narrow both
    boards at once.
    """
    rows: list[str] = [ANY_STAGE]
    for funnel in (FUNNEL_ACCOUNT, FUNNEL_DEAL):
        rows.extend(stage.id for stage in funnel_stages(funnel))
    return rows


def render_toolbar(
    *,
    districts: Iterable[str] = (),
    managers: Iterable[str] = (),
    prefix: str = "hydro_filter",
) -> dict[str, Any]:
    """Draw the toolbar and return the selected filters."""
    district_rows = tuple(districts)
    manager_rows = tuple(managers)
    with st.container(horizontal=True, gap="small", vertical_alignment="bottom"):
        query = st.text_input(
            "Поиск УК / адрес / ИНН",
            key=f"{prefix}_query",
            placeholder="например Жилищник",
            width=210,
        )
        district = ALL_DISTRICTS
        if district_rows:
            district = st.selectbox(
                "Район / округ",
                (ALL_DISTRICTS,) + district_rows,
                index=0,
                key=f"{prefix}_district",
                width=165,
            )
        responsible = ALL_MANAGERS
        if manager_rows:
            responsible = st.selectbox(
                "Менеджер",
                (ALL_MANAGERS,) + manager_rows,
                index=0,
                key=f"{prefix}_responsible",
                width=165,
            )
        stage = st.selectbox(
            "Статус",
            stage_options(),
            index=0,
            format_func=lambda value: STAGE_LABELS.get(value, "Все статусы"),
            key=f"{prefix}_stage",
            width=185,
        )
        overdue = st.toggle("Только просроченные", key=f"{prefix}_overdue", width=155)
        active_only = st.toggle(
            "Только с активными", key=f"{prefix}_active", width=140,
            help="УК с реальными объектами; объекты — уже взятые в работу.",
        )
        if st.button("Сброс", key=f"{prefix}_reset", width=90):
            reset_filters(prefix)
            st.rerun()
    return {
        "query": str(query or "").strip(),
        "district": ALL_DISTRICTS if district == ALL_DISTRICTS else str(district),
        "responsible": responsible,
        "stage": stage,
        "overdue": bool(overdue),
        "active_only": bool(active_only),
    }


__all__ = [
    "ALL_DISTRICTS",
    "ALL_MANAGERS",
    "ANY_STAGE",
    "reset_filters",
    "render_toolbar",
    "stage_options",
]
