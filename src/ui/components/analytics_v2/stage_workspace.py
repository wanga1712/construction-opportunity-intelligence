"""Shared scan-list/detail workspace for analytical-contour lifecycle stages."""
from __future__ import annotations

from typing import Any

import streamlit as st

from src.services.annotation_card_provenance import source_law
from src.ui.components.analytics_v2.annotation_queue import ACTIVE_QUEUE_KEY
from src.ui.components.analytics_v2.card_trust import fmt_date, fmt_price


def _stage_amount(card: dict, stage: str) -> tuple[Any, str]:
    if stage == "AWARDED" and card.get("final_contract_price") is not None:
        return card.get("final_contract_price"), "Цена контракта"
    return card.get("initial_price"), "НМЦК"


def _stage_deadline(card: dict, stage: str) -> tuple[Any, str]:
    if stage == "AWARDED":
        return card.get("execution_end_at") or card.get("delivery_end_date"), "Исполнение до"
    if stage == "COMMISSION":
        return card.get("end_date"), "Приём заявок завершён"
    return card.get("end_date"), "Приём заявок до"


def render_stage_list_card(
    card: dict,
    idx: int,
    *,
    session_key: str,
    stage: str,
    effective: Any = None,
) -> None:
    """Render a cheap scan card. No document resolver or per-card DB query."""
    amount, amount_label = _stage_amount(card, stage)
    deadline, deadline_label = _stage_deadline(card, stage)
    medal = getattr(effective, "best_candidate_level", None) if effective else None
    scope = getattr(effective, "business_relevance", None) if effective else None
    model_status = getattr(effective, "ai_status", None) if effective else None
    law = source_law(card.get("source_table"))

    with st.container(border=True):
        st.markdown(f"#### {card.get('auction_name') or 'Закупка без названия'}")
        amount_col, deadline_col, law_col = st.columns(3)
        amount_col.markdown(f"**{fmt_price(amount)}**  \n{amount_label}")
        deadline_col.markdown(f"**{fmt_date(deadline)}**  \n{deadline_label}")
        law_col.markdown(f"**{law}**  \nИсточник")
        st.caption(
            f"Заказчик: {card.get('customer') or '—'} · "
            f"Регион: {card.get('delivery_region') or '—'}"
        )
        signals = [value for value in (medal, scope, model_status, card.get("crm_category")) if value]
        if signals:
            st.caption(" · ".join(map(str, signals)))
        if st.button(
            "Открыть карточку",
            key=f"open_stage_card_{session_key}_{card.get('id')}_{idx}",
            type="primary",
        ):
            st.session_state[session_key] = card["id"]
            st.session_state[ACTIVE_QUEUE_KEY] = session_key
            st.rerun()


def render_stage_workspace(
    cards: list[dict],
    *,
    session_key: str,
    stage: str,
    stage_label: str,
    effective_map: dict | None = None,
) -> str:
    """Switch one stage between scan list and the accepted full annotation card."""
    effective_map = effective_map or {}
    ids = [card["id"] for card in cards]
    selected_id = st.session_state.get(session_key)
    if selected_id is not None and selected_id not in ids:
        st.session_state.pop(session_key, None)
        if st.session_state.get(ACTIVE_QUEUE_KEY) == session_key:
            st.session_state.pop(ACTIVE_QUEUE_KEY, None)
        selected_id = None

    if selected_id is None:
        for idx, card in enumerate(cards):
            render_stage_list_card(
                card,
                idx,
                session_key=session_key,
                stage=stage,
                effective=effective_map.get(card["id"]),
            )
        return "LIST"

    st.session_state[ACTIVE_QUEUE_KEY] = session_key
    if st.button(f"← Назад к списку · {stage_label}", key=f"back_to_stage_{session_key}"):
        st.session_state.pop(session_key, None)
        st.session_state.pop(ACTIVE_QUEUE_KEY, None)
        st.rerun()

    _render_selected_detail(selected_id)
    return "DETAIL"


def _render_selected_detail(selected_id: int) -> None:
    """Load the expensive full-card layers for one selected procurement only."""
    from src.services.annotation_queue_service import (
        batch_publication_visibility,
        fetch_procurement_header,
        lifecycle_label,
    )
    from src.services.db_bootstrap import connect_databases
    from src.services.expert_annotation_service import (
        load_expert_annotation,
        load_model_assessment_for_annotation,
    )
    from src.ui.components.analytics_v2.annotation_card import render_annotation_card

    _, _, crm_db, _ = connect_databases()
    header = fetch_procurement_header(crm_db, selected_id)
    if not header:
        st.error("Закупка не найдена")
        return "DETAIL_MISSING"
    render_annotation_card(
        crm_db=crm_db,
        procurement_id=selected_id,
        header=header,
        assessment=load_model_assessment_for_annotation(selected_id, crm_db),
        existing_annotation=load_expert_annotation(selected_id, crm_db),
        publication_visible=batch_publication_visibility(crm_db, [selected_id]).get(
            selected_id, False
        ),
        lifecycle_label=lifecycle_label(header),
    )
