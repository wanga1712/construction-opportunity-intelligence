"""Shared lazy inline-card workspace for analytical lifecycle feeds."""
from __future__ import annotations
from typing import Any
import streamlit as st
from src.services.annotation_card_provenance import source_law
from src.services.annotation_state_service import ANNOTATED, NOT_INTERESTING, UNANNOTATED, annotation_state_counts, load_current_annotation_states
from src.ui.components.analytics_v2.card_trust import fmt_date, fmt_price

SECTIONS = ("Обзор", "Модель / Категории", "Документы", "История", "Экспертная разметка")
FILTERS = (("ALL", "Все"), (UNANNOTATED, "Не размеченные"), (ANNOTATED, "Размеченные"), (NOT_INTERESTING, "Неинтересные"))

def _activate_inline(active_key: str, procurement_id: int) -> None:
    st.session_state[active_key] = procurement_id

def _amount(card: dict, stage: str):
    return ((card.get("final_contract_price"), "Цена контракта") if stage == "AWARDED" and card.get("final_contract_price") is not None else (card.get("initial_price"), "НМЦК"))

def _deadline(card: dict, stage: str):
    if stage == "AWARDED": return card.get("execution_end_at") or card.get("delivery_end_date"), "Исполнение до"
    return card.get("end_date"), "Приём заявок завершён" if stage == "COMMISSION" else "Приём заявок до"

def _summary(card: dict, stage: str, effective: Any, state: dict) -> None:
    amount, amount_label = _amount(card, stage); deadline, deadline_label = _deadline(card, stage)
    badge = {UNANNOTATED: "Не размечено", ANNOTATED: "Размечено", NOT_INTERESTING: "Неинтересная"}[state["annotation_state"]]
    medal = getattr(effective, "best_candidate_level", None) if effective else None
    business = getattr(effective, "business_relevance", None) if effective else None
    ai = getattr(effective, "ai_status", None) if effective else None
    st.caption(f"{medal or '—'} · 👤 {badge} · {stage}")
    st.markdown(f"#### {card.get('auction_name') or 'Закупка без названия'}")
    a, d, law = st.columns(3); a.metric(amount_label, fmt_price(amount)); d.metric(deadline_label, fmt_date(deadline)); law.metric("Источник", source_law(card.get("source_table")))
    st.markdown(f"**Заказчик:** {card.get('customer') or '—'}  \n**Регион:** {card.get('delivery_region') or '—'}")
    if stage == "AWARDED" and card.get("contractor_name"): st.markdown(f"**Подрядчик / победитель:** {card['contractor_name']}")
    st.caption(f"AI: {ai or '—'} · Business: {business or '—'} · route: {card.get('proposed_route_profile') or '—'} · object: {card.get('proposed_object_type') or '—'} · category: {card.get('crm_category') or '—'} · confidence: {card.get('confidence') or '—'} · files/matches/evidence: {card.get('file_count') or 0}/{card.get('match_count') or 0}/{card.get('evidence_count') or 0}")

def render_stage_workspace(cards: list[dict], *, session_key: str, stage: str, stage_label: str, effective_map: dict | None = None) -> str:
    from src.services.db_bootstrap import connect_databases
    _, _, crm_db, _ = connect_databases()
    states = load_current_annotation_states([c["id"] for c in cards], crm_db); counts = annotation_state_counts(states)
    filter_key = f"annotation_state_filter_{session_key}"; labels = [f"{label} · {counts[key]}" for key, label in FILTERS]
    selected_label = st.radio("Экспертная разметка", labels, horizontal=True, key=filter_key)
    selected_state = FILTERS[labels.index(selected_label)][0]
    visible = cards if selected_state == "ALL" else [c for c in cards if states[c["id"]]["annotation_state"] == selected_state]
    active_key = f"active_inline_{session_key}"
    focused = st.session_state.get(session_key)
    if focused in [card["id"] for card in visible]:
        st.session_state[active_key] = focused
        st.session_state[f"inline_card_tab_{focused}"] = "Экспертная разметка"
    for card in visible:
        pid = card["id"]
        with st.container(border=True):
            _summary(card, stage, (effective_map or {}).get(pid), states[pid])
            section = st.radio("Раздел карточки", SECTIONS, horizontal=True, key=f"inline_card_tab_{pid}", on_change=_activate_inline, args=(active_key, pid))
            if section == "Обзор":
                if card.get("tender_link"): st.link_button("🔗 Открыть закупку", card["tender_link"])
            elif st.session_state.get(active_key) == pid:
                _render_expensive_section(pid, section)
            else: st.caption("Другой карточке принадлежит активный рабочий фокус.")
    return "INLINE"

def _render_expensive_section(procurement_id: int, section: str) -> None:
    from src.services.annotation_queue_service import fetch_procurement_header
    from src.services.db_bootstrap import connect_databases
    from src.services.expert_annotation_service import load_expert_annotation, load_model_assessment_for_annotation
    from src.ui.components.analytics_v2.annotation_card import render_annotation_section
    _, _, crm_db, _ = connect_databases(); header = fetch_procurement_header(crm_db, procurement_id)
    render_annotation_section(crm_db=crm_db, procurement_id=procurement_id, header=header, assessment=load_model_assessment_for_annotation(procurement_id, crm_db), existing_annotation=load_expert_annotation(procurement_id, crm_db), section=section)
