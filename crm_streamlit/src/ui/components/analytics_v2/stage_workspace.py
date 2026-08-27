"""Shared lazy inline-card workspace for analytical lifecycle feeds."""
from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from src.services.annotation_category_gate import (
    FIRST_GATE_QUESTION,
    IN_CATEGORY,
    LEGACY_NEGATIVE_BADGE,
    LEGACY_NOT_INTERESTING,
    OUT_OF_CATEGORY,
    OUT_OF_CATEGORY_BADGE,
    UNCERTAIN,
    build_out_of_category_payload,
    build_uncertain_payload,
)
from src.services.annotation_staged import staged_card_summary
from src.services.annotation_state_service import (
    REVIEWED,
    UNREVIEWED,
    annotation_state_counts,
    load_current_annotation_states,
)
from src.services.expert_commercial_entry import NON_COMMERCIAL
from src.services.expert_medal_stage import BRONZE, GOLD, SILVER, WOOD
from src.services.source_contour import resolve_source_contour
from src.ui.components.analytics_v2.card_trust import fmt_date, fmt_price

SECTIONS = ("Обзор", "Модель / Категории", "Документы", "История", "Экспертная разметка")
# Primary: category triage. Secondary: IN_CATEGORY medal/commercial subset + legacy.
FILTERS = (
    ("ALL", "Все"),
    (UNREVIEWED, "Не проверено"),
    (IN_CATEGORY, "В категории"),
    (OUT_OF_CATEGORY, "Вне товарных категорий"),
    (UNCERTAIN, "Не уверен"),
    (GOLD, "GOLD"),
    (SILVER, "SILVER"),
    (BRONZE, "BRONZE"),
    (WOOD, "WOOD"),
    (NON_COMMERCIAL, "Коммерчески не подходит"),
    (LEGACY_NOT_INTERESTING, "Старые «Неинтересные»"),
)
AI_LABELS = {"ASSESSED": "🤖 AI оценено", "UNASSESSED": "🤖 AI не оценено",
             "INCOMPLETE": "⚠ AI оценка неполная", "FAILED": "❌ Ошибка AI"}
BUSINESS_LABELS = {"IN_PROFILE": "🟢 В профиле", "OUT_OF_PROFILE": "⚪ AI: вне профиля"}
MEDAL_LABELS = {"GOLD": "🥇 GOLD", "SILVER": "🥈 SILVER", "BRONZE": "🥉 BRONZE", "WOOD": "🪵 WOOD"}
MEDAL_FILTERS = (GOLD, SILVER, BRONZE, WOOD)


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


def _human_chips(state: dict) -> list[str]:
    chips: list[str] = []
    scope = state.get("expert_category_scope")
    if scope == OUT_OF_CATEGORY:
        chips.append("✓ Триаж")
        chips.append(OUT_OF_CATEGORY_BADGE)
    elif scope == UNCERTAIN:
        chips.append("✓ Триаж")
        chips.append("? Не уверен (категории)")
    elif scope == IN_CATEGORY:
        if state.get("is_deep_annotation_complete"):
            chips.append("✓ Глубокая разметка")
        else:
            chips.append("👤 В категории · нужна глубокая")
        chips.append("✓ В товарных категориях")
    elif state.get("is_legacy_negative"):
        chips.append("👤 Не проверено")
        chips.append(LEGACY_NEGATIVE_BADGE)
    else:
        chips.append("👤 Не проверено")
    return chips


def _render_ai_decision_block(card: dict, effective: Any, state: dict) -> None:
    """Primary-card read-only AI decisions + expert contrast."""
    from src.services.ai_decision_summary import build_ai_decision_summary

    assessment = {
        "normalized_result": card.get("normalized_result"),
        "proposed_object_type": card.get("proposed_object_type"),
        "proposed_route_profile": card.get("proposed_route_profile"),
        "proposed_procurement_type": card.get("proposed_procurement_type"),
        "confidence": card.get("confidence"),
        "reasons": card.get("reasons"),
    }
    if effective is not None:
        nr = getattr(effective, "normalized_result", None)
        if nr:
            assessment["normalized_result"] = nr
        for attr in (
            "validated_model_result",
            "business_rule_result",
            "inference_run_id",
            "model_provenance",
            "proposed_object_type",
            "proposed_route_profile",
        ):
            val = getattr(effective, attr, None)
            if val is not None:
                assessment[attr] = val

    summary = build_ai_decision_summary(assessment)
    st.markdown("**🤖 ИИ предложил**")
    for label, value in summary["fields"]:
        st.caption(f"{label}: {value}")
    st.caption("Только чтение. Исправление — в блоке экспертной разметки ниже.")

    scope = state.get("expert_category_scope")
    if scope or state.get("is_category_reviewed"):
        st.markdown("**👤 Эксперт**")
        if scope == OUT_OF_CATEGORY:
            st.caption("Товарная принадлежность: Вне товарных категорий")
        elif scope == IN_CATEGORY:
            st.caption("Товарная принадлежность: В товарных категориях")
            if state.get("expert_category_codes"):
                st.caption("Категория: " + ", ".join(state["expert_category_codes"]))
        elif scope == UNCERTAIN:
            st.caption("Товарная принадлежность: Не уверен")
        if state.get("expert_object_type"):
            st.caption(f"Объект: {state.get('expert_object_type')}")
        if state.get("expert_procurement_mode"):
            st.caption(f"Режим закупки: {state.get('expert_procurement_mode')}")
        if state.get("expert_commercial_entry"):
            st.caption(f"Коммерция: {state.get('expert_commercial_entry')}")
        if state.get("expert_medal"):
            st.caption(f"Medal: {state.get('expert_medal')}")
    else:
        st.markdown("**👤 Эксперт:** не проверено")


def _render_structured_result(state: dict) -> None:
    summary = staged_card_summary(state.get("payload"))
    if summary["status"] == "UNREVIEWED":
        st.caption("👤 Не проверено")
        return
    titles = {
        "REVIEWED": "👤 Глубокая разметка завершена",
        "TRIAGED": "👤 Триаж категорий",
        "PARTIAL": "👤 Частично · нужно дополнить",
    }
    st.markdown(f"**{titles.get(summary['status'], '👤 Разметка')}**")
    for label, value in summary["lines"]:
        st.markdown(f"{label}: **{escape(str(value))}**", unsafe_allow_html=True)


def _summary(card: dict, stage: str, effective: Any, state: dict, published: bool) -> None:
    amount, amount_label = _amount(card, stage)
    deadline, deadline_label = _deadline(card, stage)
    medal = _clean(getattr(effective, "best_candidate_level", None) if effective else None)
    business = _clean(getattr(effective, "business_relevance", None) if effective else None)
    ai = _clean(getattr(effective, "ai_status", None) if effective else None) or "UNASSESSED"
    chips = [MEDAL_LABELS.get(medal, medal) if medal else None, *_human_chips(state),
             AI_LABELS.get(ai, f"🤖 {ai}"), BUSINESS_LABELS.get(business) if business else None,
             "✓ Опубликовано в CRM" if published else "Не опубликовано менеджерам"]
    chips.extend(filter(None, [f"📎 {card.get('file_count')} документов" if card.get("file_count") else None,
                               f"🔎 {card.get('match_count')} совпадений" if card.get("match_count") else None,
                               f"✅ {card.get('evidence_count')} подтверждений" if card.get("evidence_count") else None]))
    st.markdown(" ".join(f"`{escape(str(chip))}`" for chip in chips if chip))
    st.markdown(
        f"<div style='font-size:24px;font-weight:680;line-height:1.3;margin:.35rem 0 .6rem;overflow-wrap:anywhere'>"
        f"{escape(card.get('auction_name') or 'Закупка без названия')}</div>",
        unsafe_allow_html=True,
    )
    contour = resolve_source_contour(card.get("source_table"))
    facts = (
        ("💰", fmt_price(amount), amount_label),
        ("📅", fmt_date(deadline), deadline_label),
        ("📜", contour["card_primary"], contour["card_secondary"]),
    )
    st.markdown(
        "<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(min(145px,100%),1fr));gap:10px;width:100%'>"
        + "".join(
            f"<div style='min-width:0'><b style='font-size:20px;white-space:nowrap'>{icon} {escape(str(value))}</b>"
            f"<br><small>{escape(label)}</small></div>"
            for icon, value, label in facts
        )
        + "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"🏢 {escape(str(card.get('customer') or '—'))} &nbsp;&nbsp; "
        f"📍 {escape(str(card.get('delivery_region') or '—'))}",
        unsafe_allow_html=True,
    )
    value = format_okpd_preview(card)
    if value:
        st.markdown(f"🏷 **ОКПД2:** {escape(value)}", unsafe_allow_html=True)
    else:
        st.caption("ОКПД2: не указан в карточке")
    if stage == "AWARDED" and card.get("contractor_name"):
        st.markdown(f"**Подрядчик / победитель:** {card['contractor_name']}")
    _render_ai_decision_block(card, effective, state)
    if state.get("is_category_reviewed") or state.get("is_partial"):
        _render_structured_result(state)


def _source_actions(card: dict) -> None:
    from src.services.procurement_identity import resolve_procurement_link

    view = resolve_procurement_link(
        source_table=card.get("source_table"),
        contract_number=card.get("contract_number"),
        tender_link=card.get("tender_link"),
    )
    if view.procurement_number:
        st.markdown(f"📋 **№ закупки:** `{view.procurement_number}`")
    if view.render_direct_link and view.public_url:
        st.link_button("🔗 Закупка на ЕИС", view.public_url)
    else:
        st.caption(view.caption or "Прямая ссылка на закупку не подтверждена")


def _filter_matches(state: dict, selected_state: str) -> bool:
    if selected_state == "ALL":
        return True
    if selected_state == UNREVIEWED:
        return not state.get("is_category_reviewed")
    if selected_state == REVIEWED:
        return bool(state.get("is_category_reviewed"))
    if selected_state == IN_CATEGORY:
        return state.get("expert_category_scope") == IN_CATEGORY
    if selected_state == OUT_OF_CATEGORY:
        return state.get("expert_category_scope") == OUT_OF_CATEGORY
    if selected_state == UNCERTAIN:
        return state.get("expert_category_scope") == UNCERTAIN
    if selected_state == NON_COMMERCIAL:
        return (
            state.get("expert_category_scope") == IN_CATEGORY
            and state.get("expert_commercial_entry") == NON_COMMERCIAL
        )
    if selected_state in MEDAL_FILTERS:
        return (
            state.get("expert_category_scope") == IN_CATEGORY
            and state.get("expert_medal") == selected_state
        )
    if selected_state == LEGACY_NOT_INTERESTING:
        return bool(state.get("is_legacy_negative"))
    return False


def render_stage_workspace(
    cards: list[dict],
    *,
    session_key: str,
    stage: str,
    stage_label: str,
    effective_map: dict | None = None,
    workset_ids: list[int] | None = None,
    annotation_states: dict[int, dict] | None = None,
    selected_annotation_filter: str | None = None,
) -> str:
    from src.services.annotation_queue_service import batch_publication_visibility
    from src.services.db_bootstrap import connect_databases

    _, _, crm_db, _ = connect_databases()
    all_ids = workset_ids or [card["id"] for card in cards]
    all_states = annotation_states or load_current_annotation_states(all_ids, crm_db)
    page_states = {card["id"]: all_states[card["id"]] for card in cards}
    publication = batch_publication_visibility(crm_db, [card["id"] for card in cards])
    selected_state = selected_annotation_filter or render_review_filter(all_states, session_key)
    visible = [card for card in cards if _filter_matches(page_states[card["id"]], selected_state)]
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
            _render_first_decision_gate(pid, page_states[pid], active_key, card=card, session_key=session_key)
            section_labels = list(SECTIONS)
            section_labels[2] = f"Документы · {card.get('file_count') or 0}"
            section = st.pills(
                "Раздел карточки",
                section_labels,
                default=section_labels[0],
                key=f"inline_card_tab_{pid}",
                label_visibility="collapsed",
                on_change=_activate_inline,
                args=(active_key, pid),
            )
            canonical_section = "Документы" if section.startswith("Документы") else section
            if canonical_section != "Обзор" and st.session_state.get(active_key) == pid:
                _render_expensive_section(pid, canonical_section)
    return "INLINE"


def render_review_filter(states: dict[int, dict], session_key: str, *, on_change=None) -> str:
    """Render persisted review progress/outcome counters and return the selected key."""
    counts = annotation_state_counts(states)
    labels = [f"{label} · {counts.get(key, 0)}" for key, label in FILTERS]
    selected_label = st.pills(
        "Эксперт",
        labels,
        default=labels[0],
        key=f"annotation_state_filter_{session_key}",
        on_change=on_change,
    )
    return FILTERS[labels.index(selected_label)][0]


def filtered_review_ids(states: dict[int, dict], selected_state: str) -> list[int]:
    return [pid for pid, state in states.items() if _filter_matches(state, selected_state)]


def _render_expensive_section(procurement_id: int, section: str) -> None:
    from src.services.annotation_queue_service import fetch_procurement_header
    from src.services.db_bootstrap import connect_databases
    from src.services.expert_annotation_service import load_expert_annotation, load_model_assessment_for_annotation
    from src.ui.components.analytics_v2.annotation_card import render_annotation_section

    _, _, crm_db, _ = connect_databases()
    header = fetch_procurement_header(crm_db, procurement_id)
    render_annotation_section(
        crm_db=crm_db,
        procurement_id=procurement_id,
        header=header,
        assessment=load_model_assessment_for_annotation(procurement_id, crm_db),
        existing_annotation=load_expert_annotation(procurement_id, crm_db),
        section=section,
    )


def _persist_fast_triage(procurement_id: int, *, out_of_category: bool) -> None:
    """One-action OUT/UNCERTAIN: persist sparse row and advance — no deep fields."""
    from src.services.db_bootstrap import connect_databases
    from src.services.expert_annotation_service import load_model_assessment_for_annotation
    from src.ui.components.analytics_v2.annotation_card import _persist, scope_decision_key

    created_by = st.session_state.get("user_name") or "expert"
    _, _, crm_db, _ = connect_databases()
    assessment = load_model_assessment_for_annotation(procurement_id, crm_db)
    if out_of_category:
        st.session_state[scope_decision_key(procurement_id)] = "NO"
        payload = build_out_of_category_payload(assessment=assessment, created_by=created_by)
    else:
        st.session_state[scope_decision_key(procurement_id)] = "UNCERTAIN"
        payload = build_uncertain_payload(assessment=assessment, created_by=created_by)
    _persist(procurement_id, payload, assessment, created_by, crm_db, save_and_next=True)


def _render_legacy_reclassify(procurement_id: int, active_key: str) -> None:
    """Fast reclassification for legacy negatives — preserve as separate state until reviewed."""
    from src.ui.components.analytics_v2.annotation_card import scope_decision_key
    from src.ui.components.analytics_v2.annotation_queue import GO_NEXT_FROM_KEY, GO_NEXT_KEY

    st.info("Старая метка: **Неинтересная**. Новая классификация (триаж товарных категорий):")
    c1, c2, c3 = st.columns(3)
    if c1.button("Вне товарных категорий", key=f"legacy_out_{procurement_id}", use_container_width=True):
        _persist_fast_triage(procurement_id, out_of_category=True)
        return
    if c2.button("Не относится только по другой причине", key=f"legacy_other_{procurement_id}", use_container_width=True):
        from src.services.db_bootstrap import connect_databases
        from src.services.expert_annotation_service import load_model_assessment_for_annotation
        from src.ui.components.analytics_v2.annotation_card import _persist

        created_by = st.session_state.get("user_name") or "expert"
        _, _, crm_db, _ = connect_databases()
        assessment = load_model_assessment_for_annotation(procurement_id, crm_db)
        payload = build_uncertain_payload(
            assessment=assessment,
            created_by=created_by,
            comment="LEGACY_OTHER_REASON_NOT_CATEGORY",
        )
        _persist(procurement_id, payload, assessment, created_by, crm_db, save_and_next=True)
        return
    if c3.button("Не уверен", key=f"legacy_unsure_{procurement_id}", use_container_width=True):
        _persist_fast_triage(procurement_id, out_of_category=False)
        return
    if st.button("Пересмотреть: относится к категориям →", key=f"legacy_yes_{procurement_id}"):
        st.session_state[scope_decision_key(procurement_id)] = "YES"
        st.session_state[active_key] = procurement_id
        st.session_state[GO_NEXT_KEY] = False
        st.session_state.pop(GO_NEXT_FROM_KEY, None)


def _render_first_decision_gate(
    procurement_id: int,
    state: dict,
    active_key: str,
    *,
    card: dict | None = None,
    session_key: str | None = None,
) -> None:
    """Fast category triage on card surface; deep annotation only after YES."""
    from src.ui.components.analytics_v2.annotation_card import scope_decision_key
    from src.ui.components.analytics_v2.staged_annotation_ui import render_source_contour_banner

    key = scope_decision_key(procurement_id)
    if not st.session_state.get(key) and state.get("expert_category_scope"):
        mapping = {IN_CATEGORY: "YES", OUT_OF_CATEGORY: "NO", UNCERTAIN: "UNCERTAIN"}
        st.session_state[key] = mapping.get(state["expert_category_scope"])

    st.markdown("---")
    st.markdown("##### 👤 ЭКСПЕРТНАЯ РАЗМЕТКА")
    render_source_contour_banner((card or {}).get("source_table"))

    if state.get("is_legacy_negative") and not state.get("is_category_reviewed"):
        _render_legacy_reclassify(procurement_id, active_key)
        if st.session_state.get(key) == "YES" and st.session_state.get(active_key) == procurement_id:
            _render_expensive_section(procurement_id, "Первое решение")
        return

    st.caption("Быстрый триаж: title + ОКПД2. Глубокая разметка — только для «В категории».")
    is_active = st.session_state.get(active_key) == procurement_id
    scope = state.get("expert_category_scope")
    decision = st.session_state.get(key)

    # Already triaged OUT/UNCERTAIN — compact, optional edit.
    if scope in (OUT_OF_CATEGORY, UNCERTAIN) and not is_active:
        if scope == OUT_OF_CATEGORY:
            st.error(OUT_OF_CATEGORY_BADGE)
        else:
            st.warning("? Товарная принадлежность: не уверен")
        if st.button("Изменить триаж", key=f"edit_triage_{procurement_id}"):
            st.session_state[active_key] = procurement_id
            st.rerun()
        return

    # IN_CATEGORY deep complete — optional edit.
    if state.get("is_deep_annotation_complete") and not is_active:
        if st.button("Изменить разметку", key=f"edit_staged_{procurement_id}"):
            st.session_state[active_key] = procurement_id
            st.rerun()
        return

    # IN_CATEGORY incomplete deep — continue deep path.
    if scope == IN_CATEGORY and not state.get("is_deep_annotation_complete"):
        if not is_active:
            if st.button(
                "Продолжить глубокую разметку →",
                key=f"continue_deep_{procurement_id}",
                type="primary",
            ):
                st.session_state[key] = "YES"
                st.session_state[active_key] = procurement_id
                st.rerun()
            return
        _render_expensive_section(procurement_id, "Первое решение")
        return

    # YES already chosen — open deep annotation only (gate lives inside form for edit).
    if decision == "YES" and is_active:
        _render_expensive_section(procurement_id, "Первое решение")
        return

    # Surface fast triage for unreviewed cards.
    if not scope:
        st.markdown(f"**1. {FIRST_GATE_QUESTION}**")
        yes, no, unsure = st.columns(3)
        if yes.button("✓ Да", key=f"fast_yes_{procurement_id}", use_container_width=True):
            st.session_state[key] = "YES"
            st.session_state[active_key] = procurement_id
            st.rerun()
            return
        if no.button("✕ Нет", key=f"fast_no_{procurement_id}", use_container_width=True):
            _persist_fast_triage(procurement_id, out_of_category=True)
            return
        if unsure.button("? Не уверен", key=f"fast_unc_{procurement_id}", use_container_width=True):
            _persist_fast_triage(procurement_id, out_of_category=False)
            return
        return

    # Active edit of prior OUT/UNCERTAIN — reopen full gate form.
    if is_active:
        _render_expensive_section(procurement_id, "Первое решение")
