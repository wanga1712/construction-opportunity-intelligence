"""Shared lazy inline-card workspace for analytical lifecycle feeds."""
from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import urlparse

import streamlit as st

from src.services.annotation_card_provenance import source_law
from src.services.annotation_state_service import (
    NOT_INTERESTING, REVIEWED, UNREVIEWED, annotation_state_counts,
    load_current_annotation_states,
)
from src.ui.components.analytics_v2.card_trust import fmt_date, fmt_price

SECTIONS = ("Обзор", "Модель / Категории", "Документы", "История", "Экспертная разметка")
FILTERS = (("ALL", "Все"), (UNREVIEWED, "Не проверено"),
           (REVIEWED, "Проверено"), (NOT_INTERESTING, "Неинтересные"))
AI_LABELS = {"ASSESSED": "🤖 AI оценено", "UNASSESSED": "🤖 AI не оценено",
             "INCOMPLETE": "⚠ AI оценка неполная", "FAILED": "❌ Ошибка AI"}
BUSINESS_LABELS = {"IN_PROFILE": "🟢 В профиле", "OUT_OF_PROFILE": "⚪ AI: вне профиля"}
MEDAL_LABELS = {"GOLD": "🥇 GOLD", "SILVER": "🥈 SILVER", "BRONZE": "🥉 BRONZE", "WOOD": "🪵 WOOD"}


def _activate_inline(active_key: str, procurement_id: int) -> None:
    st.session_state[active_key] = procurement_id


def _amount(card: dict, stage: str):
    if stage == "AWARDED" and card.get("final_contract_price") is not None:
        return card.get("final_contract_price"), "Цена контракта"
    return card.get("initial_price"), "НМЦК"


def _deadline(card: dict, stage: str):
    if stage == "AWARDED":
        return card.get("execution_end_at") or card.get("delivery_end_date"), "Исполнение до"
    return card.get("end_date"), "Приём заявок завершён" if stage == "COMMISSION" else "Приём заявок до"


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return None if not text or text.lower() in {"unknown", "unassessed", "none", "—"} else text


def format_okpd_preview(card: dict) -> str | None:
    """Compose factual already-loaded OKPD values; never invent a placeholder."""
    code = _clean(card.get("okpd_code"))
    name = _clean(card.get("okpd_name"))
    return " — ".join(filter(None, (code, name))) or None


def _summary(card: dict, stage: str, effective: Any, state: dict, published: bool) -> None:
    amount, amount_label = _amount(card, stage)
    deadline, deadline_label = _deadline(card, stage)
    human = ["✓ Проверено"] if state.get("has_annotation") else ["👤 Не проверено"]
    if state.get("is_not_interesting") or state.get("annotation_state") == NOT_INTERESTING:
        human.append("⛔ Неинтересная")
    medal = _clean(getattr(effective, "best_candidate_level", None) if effective else None)
    business = _clean(getattr(effective, "business_relevance", None) if effective else None)
    ai = _clean(getattr(effective, "ai_status", None) if effective else None) or "UNASSESSED"
    chips = [MEDAL_LABELS.get(medal, medal) if medal else None, *human,
             AI_LABELS.get(ai, f"🤖 {ai}"), BUSINESS_LABELS.get(business) if business else None,
             "✓ Опубликовано в CRM" if published else "Не опубликовано менеджерам"]
    for icon, value in (("📦", card.get("crm_category")), ("🏗", card.get("proposed_object_type")),
                        ("🛠", card.get("proposed_procurement_type"))):
        if _clean(value): chips.append(f"{icon} {_clean(value)}")
    chips.extend(filter(None, [f"📎 {card.get('file_count')} документов" if card.get("file_count") else None,
                               f"🔎 {card.get('match_count')} совпадений" if card.get("match_count") else None,
                               f"✅ {card.get('evidence_count')} подтверждений" if card.get("evidence_count") else None]))
    st.markdown(" ".join(f"`{escape(str(chip))}`" for chip in chips if chip))
    st.markdown(f"<div style='font-size:24px;font-weight:680;line-height:1.3;margin:.35rem 0 .6rem;overflow-wrap:anywhere'>{escape(card.get('auction_name') or 'Закупка без названия')}</div>", unsafe_allow_html=True)
    facts = (("💰", fmt_price(amount), amount_label), ("📅", fmt_date(deadline), deadline_label),
             ("📜", source_law(card.get("source_table")), "Источник"))
    st.markdown("<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(min(145px,100%),1fr));gap:10px;width:100%'>" + "".join(
        f"<div style='min-width:0'><b style='font-size:20px;white-space:nowrap'>{icon} {escape(str(value))}</b><br><small>{escape(label)}</small></div>"
        for icon, value, label in facts) + "</div>", unsafe_allow_html=True)
    st.markdown(f"🏢 {escape(str(card.get('customer') or '—'))} &nbsp;&nbsp; 📍 {escape(str(card.get('delivery_region') or '—'))}", unsafe_allow_html=True)
    value = format_okpd_preview(card)
    if value:
        st.markdown(f"🏷 **ОКПД2:** {escape(value)}", unsafe_allow_html=True)
    if stage == "AWARDED" and card.get("contractor_name"):
        st.markdown(f"**Подрядчик / победитель:** {card['contractor_name']}")


def _source_actions(card: dict) -> None:
    url = _clean(card.get("tender_link"))
    if url:
        host = (urlparse(url).hostname or "").lower()
        st.link_button("🔗 Закупка на ЕИС" if "zakupki.gov.ru" in host else "🔗 Открыть закупку", url)
    else:
        st.caption("🔗 Ссылка на закупку отсутствует")


def render_stage_workspace(cards: list[dict], *, session_key: str, stage: str,
                           stage_label: str, effective_map: dict | None = None,
                           workset_ids: list[int] | None = None,
                           annotation_states: dict[int, dict] | None = None,
                           selected_annotation_filter: str | None = None) -> str:
    from src.services.annotation_queue_service import batch_publication_visibility
    from src.services.db_bootstrap import connect_databases
    _, _, crm_db, _ = connect_databases()
    all_ids = workset_ids or [card["id"] for card in cards]
    all_states = annotation_states or load_current_annotation_states(all_ids, crm_db)
    page_states = {card["id"]: all_states[card["id"]] for card in cards}
    publication = batch_publication_visibility(crm_db, [card["id"] for card in cards])
    selected_state = selected_annotation_filter or render_review_filter(all_states, session_key)
    def included(state: dict) -> bool:
        if selected_state == "ALL": return True
        if selected_state == UNREVIEWED: return not state.get("has_annotation")
        if selected_state == REVIEWED: return bool(state.get("has_annotation"))
        return bool(state.get("is_not_interesting") or state.get("annotation_state") == NOT_INTERESTING)
    visible = [card for card in cards if included(page_states[card["id"]])]
    active_key = f"active_inline_{session_key}"
    focused = st.session_state.get(session_key)
    if focused in [card["id"] for card in visible]:
        st.session_state[active_key] = focused
        st.session_state[f"inline_card_tab_{focused}"] = "Экспертная разметка"
    for card in visible:
        pid = card["id"]
        with st.container(border=True):
            _summary(card, stage, (effective_map or {}).get(pid), page_states[pid], publication.get(pid, False))
            _source_actions(card)
            _render_first_decision_gate(pid, page_states[pid], active_key)
            section_labels = list(SECTIONS); section_labels[2] = f"Документы · {card.get('file_count') or 0}"
            section = st.pills("Раздел карточки", section_labels, default=section_labels[0],
                               key=f"inline_card_tab_{pid}", label_visibility="collapsed",
                               on_change=_activate_inline, args=(active_key, pid))
            canonical_section = "Документы" if section.startswith("Документы") else section
            if canonical_section != "Обзор" and st.session_state.get(active_key) == pid:
                _render_expensive_section(pid, canonical_section)
    return "INLINE"


def render_review_filter(states: dict[int, dict], session_key: str, *, on_change=None) -> str:
    """Render persisted review progress/outcome counters and return the selected key."""
    counts = annotation_state_counts(states)
    labels = [f"{label} · {counts[key]}" for key, label in FILTERS]
    selected_label = st.pills(
        "Эксперт",
        labels,
        default=labels[0],
        key=f"annotation_state_filter_{session_key}",
        on_change=on_change,
    )
    return FILTERS[labels.index(selected_label)][0]


def filtered_review_ids(states: dict[int, dict], selected_state: str) -> list[int]:
    if selected_state == "ALL":
        return list(states)
    if selected_state == UNREVIEWED:
        return [pid for pid, state in states.items() if not state.get("has_annotation")]
    if selected_state == REVIEWED:
        return [pid for pid, state in states.items() if state.get("has_annotation")]
    return [
        pid for pid, state in states.items()
        if state.get("is_not_interesting") or state.get("annotation_state") == NOT_INTERESTING
    ]


def _render_expensive_section(procurement_id: int, section: str) -> None:
    from src.services.annotation_queue_service import fetch_procurement_header
    from src.services.db_bootstrap import connect_databases
    from src.services.expert_annotation_service import load_expert_annotation, load_model_assessment_for_annotation
    from src.ui.components.analytics_v2.annotation_card import render_annotation_section
    _, _, crm_db, _ = connect_databases()
    header = fetch_procurement_header(crm_db, procurement_id)
    render_annotation_section(crm_db=crm_db, procurement_id=procurement_id, header=header,
                              assessment=load_model_assessment_for_annotation(procurement_id, crm_db),
                              existing_annotation=load_expert_annotation(procurement_id, crm_db), section=section)


def _render_first_decision_gate(procurement_id: int, state: dict, active_key: str) -> None:
    """Keep the fastest human decision on the card surface; load writes lazily."""
    from src.ui.components.analytics_v2.annotation_card import scope_decision_key

    key = scope_decision_key(procurement_id)
    st.markdown("---")
    st.markdown("##### 👤 ЭКСПЕРТНАЯ ПРОВЕРКА")
    st.markdown("**1. Закупка относится к нашему профилю?**")
    yes, no, unsure = st.columns(3)
    clicked = None
    if yes.button("✓ Да", key=f"scope_yes_{procurement_id}", use_container_width=True):
        clicked = "YES"
    if no.button("✕ Нет", key=f"scope_no_{procurement_id}", use_container_width=True):
        clicked = "NO"
    if unsure.button("? Не уверен", key=f"scope_uncertain_{procurement_id}", use_container_width=True):
        clicked = "UNCERTAIN"
    if clicked:
        st.session_state[key] = clicked
        st.session_state[active_key] = procurement_id
    if st.session_state.get(key) and st.session_state.get(active_key) == procurement_id:
        _render_expensive_section(procurement_id, "Первое решение")
