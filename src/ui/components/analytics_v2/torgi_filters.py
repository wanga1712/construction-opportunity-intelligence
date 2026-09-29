"""Filter toolbar for the Torgi stage in Analytics Contour V2."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional
import streamlit as st

from src.services.torgi_workset_service import TorgiFilterParams

EFFECTIVE_MEDAL_OPTIONS = ["Все", "GOLD", "SILVER", "BRONZE", "WOOD", "UNASSESSED"]
MODEL_MEDAL_OPTIONS = ["Все", "GOLD", "SILVER", "BRONZE", "WOOD", "UNASSESSED"]
PRELIMINARY_MEDAL_OPTIONS = ["Все", "GOLD", "SILVER", "BRONZE", "WOOD", "UNASSESSED"]
EXPERT_STATUS_OPTIONS = ["Все", "Подтверждено", "Не проверено"]
OBJECT_FAMILY_OPTIONS = ["Все", "SOCIAL", "COMMERCIAL", "DIRECT_SUPPLY", "OTHER"]


def render_torgi_filter_bar(
    session_key: str,
    on_change: Optional[Callable[[], None]] = None,
) -> TorgiFilterParams:
    """Render compact filter bar for Torgi stage and return filter parameters."""
    c1, c2, c3 = st.columns([3, 2, 2])

    with c1:
        effective_medal = st.pills(
            "Текущая оценка (с учётом срока)",
            EFFECTIVE_MEDAL_OPTIONS,
            default=EFFECTIVE_MEDAL_OPTIONS[0],
            key=f"{session_key}_effective_medal_pills",
            on_change=on_change,
        )

    with c2:
        expert_status = st.pills(
            "Экспертная оценка",
            EXPERT_STATUS_OPTIONS,
            default=EXPERT_STATUS_OPTIONS[0],
            key=f"{session_key}_expert_status_pills",
            on_change=on_change,
        )

    with c3:
        hide_expired = st.toggle(
            "Скрыть завершённые",
            value=True,
            key=f"{session_key}_hide_expired_toggle",
            on_change=on_change,
            help="Скрывает закупки с истёкшим сроком подачи или закрытым приёмом заявок",
        )

    with st.expander("Дополнительные фильтры (оценка по документам, базовая, объект, поиск)", expanded=False):
        col_model, col_prelim, col_fam, col_search = st.columns([2, 2, 2, 3])
        with col_model:
            model_medal = st.selectbox(
                "Оценка по документам (ИИ)",
                MODEL_MEDAL_OPTIONS,
                index=0,
                key=f"{session_key}_model_medal_select",
                on_change=on_change,
            )
        with col_prelim:
            prelim_medal = st.selectbox(
                "Предварительная оценка",
                PRELIMINARY_MEDAL_OPTIONS,
                index=0,
                key=f"{session_key}_prelim_medal_select",
                on_change=on_change,
            )
        with col_fam:
            object_family = st.selectbox(
                "Тип объекта (Family)",
                OBJECT_FAMILY_OPTIONS,
                index=0,
                key=f"{session_key}_obj_family_select",
                on_change=on_change,
            )
        with col_search:
            search_query = st.text_input(
                "Поиск по названию / номеру",
                value="",
                key=f"{session_key}_search_query_input",
                on_change=on_change,
            )

    return TorgiFilterParams(
        effective_medal=effective_medal if effective_medal != "Все" else None,
        model_medal=model_medal if model_medal != "Все" else None,
        preliminary_medal=prelim_medal if prelim_medal != "Все" else None,
        expert_status=expert_status if expert_status != "Все" else None,
        object_family=object_family if object_family != "Все" else None,
        search_query=search_query.strip() if search_query else None,
        hide_expired=hide_expired,
    )

