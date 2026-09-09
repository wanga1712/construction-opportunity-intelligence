"""Shared lazy inline-card workspace for analytical lifecycle feeds."""
from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from src.services.annotation_category_gate import (
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
from src.services.expert_commercial_entry import COMMERCIAL, NON_COMMERCIAL
from src.services.expert_medal_stage import BRONZE, GOLD, SILVER, WOOD
from src.services.source_contour import resolve_source_contour
from src.ui.components.analytics_v2.card_trust import fmt_date, fmt_price

SECTIONS = ("Сводка", "Возможности", "Документы", "Участники", "История", "ИИ / эксперт")
FILTERS = (
    ("ALL", "Все"),
    (UNREVIEWED, "Не проверено"),
    (REVIEWED, "Проверено"),
    (IN_CATEGORY, "В категории"),
    (OUT_OF_CATEGORY, "Вне категорий"),
    (COMMERCIAL, "Коммерчески подходит"),
    (NON_COMMERCIAL, "Коммерчески не подходит"),
    (UNCERTAIN, "Не уверен"),
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
    if state.get("is_staged_complete"):
        chips.append("✓ Проверено")
        if scope == OUT_OF_CATEGORY:
            chips.append(OUT_OF_CATEGORY_BADGE)
        elif scope == IN_CATEGORY:
            chips.append("✓ В товарных категориях")
        elif scope == UNCERTAIN:
            chips.append("? Не уверен (категории)")
    elif state.get("is_partial") or state.get("is_category_reviewed"):
        chips.append("👤 Частично · нужно дополнить")
        if scope == OUT_OF_CATEGORY:
            chips.append(OUT_OF_CATEGORY_BADGE)
    else:
        chips.append("👤 Не проверено")
        if state.get("is_legacy_negative"):
            chips.append(LEGACY_NEGATIVE_BADGE)
    return chips


def _render_structured_result(state: dict) -> None:
    summary = staged_card_summary(state.get("payload"))
    if summary["status"] == "UNREVIEWED":
        st.caption("👤 Не проверено")
        return
    title = "👤 Проверено" if summary["status"] == "REVIEWED" else "👤 Частично проверено"
    st.markdown(f"**{title}**")
    for label, value in summary["lines"]:
        st.markdown(f"{label}: **{escape(str(value))}**", unsafe_allow_html=True)


def _summary(card: dict, stage: str, effective: Any, state: dict, published: bool,
             opps: list | None = None, evidence: dict | None = None,
             entities: dict | None = None) -> None:
    amount, amount_label = _amount(card, stage)
    deadline, deadline_label = _deadline(card, stage)
    contour = resolve_source_contour(card.get("source_table"))

    # ── Status line: [law] [stage] [region] [deadline] ───────────
    law_label = contour.get("card_primary", "")
    region = card.get("delivery_region") or ""
    dl_text = fmt_date(deadline) if deadline else ""
    status_chips = [c for c in [law_label, contour.get("card_secondary", ""),
                                region, f"до {dl_text}" if dl_text else ""] if c]
    st.markdown(" ".join(f"`{escape(c)}`" for c in status_chips))

    # ── Title ────────────────────────────────────────────────────
    st.markdown(
        f"<div style='font-size:22px;font-weight:680;line-height:1.3;"
        f"margin:.2rem 0 .4rem;overflow-wrap:anywhere'>"
        f"{escape(card.get('auction_name') or 'Закупка без названия')}</div>",
        unsafe_allow_html=True,
    )

    # ── Money + EIS link (side by side) ────────────────────────────
    from src.services.procurement_identity import resolve_procurement_link
    link_view = resolve_procurement_link(
        source_table=card.get("source_table"),
        contract_number=card.get("contract_number"),
        tender_link=card.get("tender_link"),
    )
    price_html = fmt_price(amount) if amount else "—"
    col_money, col_link = st.columns([3, 1])
    with col_money:
        if stage == "AWARDED" and card.get("initial_price") and card.get("final_contract_price"):
            nmck = card["initial_price"]
            final = card["final_contract_price"]
            try:
                nmck_f, final_f = float(nmck), float(final)
                if nmck_f > 0 and final_f < nmck_f:
                    pct = (1 - final_f / nmck_f) * 100
                    st.markdown(
                        f"<div style='margin:.1rem 0'>"
                        f"<b style='font-size:22px'>КОНТРАКТ {fmt_price(final)}</b>"
                        f"<br><span style='color:#888;font-size:0.85em'>"
                        f"НМЦК {fmt_price(nmck)} · снижение {pct:.1f}%</span></div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(f"<b style='font-size:22px'>{price_html}</b>"
                                f"<br><span style='color:#888;font-size:0.85em'>"
                                f"{amount_label}</span>", unsafe_allow_html=True)
            except (ValueError, TypeError):
                st.markdown(f"<b style='font-size:22px'>{price_html}</b>"
                            f"<br><span style='color:#888;font-size:0.85em'>"
                            f"{amount_label}</span>", unsafe_allow_html=True)
        else:
            st.markdown(f"<b style='font-size:22px'>{price_html}</b>"
                        f"<br><span style='color:#888;font-size:0.85em'>"
                        f"{amount_label}</span>", unsafe_allow_html=True)
    with col_link:
        if link_view.render_direct_link and link_view.public_url:
            st.link_button("Закупка ЕИС ↗", link_view.public_url)
        elif link_view.caption:
            st.caption(link_view.caption)


    # ── Customer ─────────────────────────────────────────────────
    customer = card.get("customer")
    if customer:
        st.caption(f"🏢 {customer}")

    # ── Category opportunities (commercial assessment) ───────────
    if opps:
        from src.ui.components.analytics_v2.card_opportunities import render_card_opportunities
        render_card_opportunities(card["id"], opps, evidence or {}, entities or {})

    # ── OKPD2 (secondary metadata) ───────────────────────────────
    value = format_okpd_preview(card)
    if value:
        st.caption(f"ОКПД2 {escape(value)}")

    # ── Contractor (for awarded) ─────────────────────────────────
    if stage == "AWARDED" and card.get("contractor_name"):
        st.caption(f"Подрядчик: {card['contractor_name']}")

    # ── Structured annotation result (if reviewed) ───────────────
    if state.get("is_staged_complete") or state.get("is_partial") or state.get("is_category_reviewed"):
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
        return not state.get("is_staged_complete")
    if selected_state == REVIEWED:
        return bool(state.get("is_staged_complete"))
    if selected_state == IN_CATEGORY:
        return state.get("expert_category_scope") == IN_CATEGORY
    if selected_state == OUT_OF_CATEGORY:
        return state.get("expert_category_scope") == OUT_OF_CATEGORY
    if selected_state == UNCERTAIN:
        return (
            state.get("expert_category_scope") == UNCERTAIN
            or state.get("expert_commercial_entry") == "UNCERTAIN"
        )
    if selected_state == COMMERCIAL:
        return state.get("expert_commercial_entry") == COMMERCIAL
    if selected_state == NON_COMMERCIAL:
        return state.get("expert_commercial_entry") == NON_COMMERCIAL
    if selected_state in MEDAL_FILTERS:
        return state.get("expert_medal") == selected_state
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

    # Теневой визуальный фильтр и сортировка по приоритету исследования
    from src.ui.components.okpd_priority_widget import get_okpd_priority_compact_badge
    c_sort, c_filt = st.columns([3, 2])
    with c_sort:
        sort_by_prior = st.checkbox(
            "Сортировать по приоритету исследования (теневой режим)",
            key=f"ui_sort_priority_{session_key}",
            value=False,
        )
    with c_filt:
        band_filter = st.selectbox(
            "Фильтр корзины (теневой)",
            ["Все корзины", "GOLD", "SILVER", "BRONZE", "WOOD"],
            key=f"ui_band_filter_{session_key}",
            index=0,
        )

    if band_filter != "Все корзины":
        visible = [
            c for c in visible
            if (get_okpd_priority_compact_badge(c["id"], c.get("okpd_code")) or {}).get("band") == band_filter
        ]

    if sort_by_prior:
        def _get_sort_score(c: dict) -> float:
            b = get_okpd_priority_compact_badge(c["id"], c.get("okpd_code"))
            return b["p_research_hit"] if b else -1.0
        visible = sorted(visible, key=_get_sort_score, reverse=True)

    active_key = f"active_inline_{session_key}"
    focused = st.session_state.get(session_key)
    if focused in [card["id"] for card in visible]:
        st.session_state[active_key] = focused
        st.session_state[f"inline_card_tab_{focused}"] = "ИИ / эксперт"

    # ── Batch load category opportunities + evidence (no N+1) ────
    page_ids = [card["id"] for card in visible]
    from src.ui.components.analytics_v2.card_opportunities import (
        batch_load_evidence_preview,
        batch_load_opportunities,
        batch_load_structured_entities,
    )
    opp_map = batch_load_opportunities(page_ids, crm_db)

    # Evidence/entities only loaded if there are opportunities to annotate
    ev_map: dict = {}
    ent_map: dict = {}
    if opp_map:
        def _doc_connect():
            import psycopg2
            from src.services.crm_db_runtime import require_crm_db_connect_kwargs
            kw = dict(require_crm_db_connect_kwargs())
            kw["dbname"] = "document_intelligence"
            kw["connect_timeout"] = 5
            return psycopg2.connect(**kw)

        try:
            ev_map = batch_load_evidence_preview(page_ids, _doc_connect)
            ent_map = batch_load_structured_entities(page_ids, _doc_connect)
        except Exception:
            pass

    for card in visible:
        pid = card["id"]
        with st.container(border=True):
            _summary(card, stage, (effective_map or {}).get(pid), page_states[pid],
                     publication.get(pid, False),
                     opps=opp_map.get(pid),
                     evidence=ev_map,
                     entities=ent_map)
            # Procurement number as lightweight caption (EIS link is inline with money)
            if card.get("contract_number"):
                st.caption(f"№ {card['contract_number']}")
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
            if canonical_section != "Сводка" and st.session_state.get(active_key) == pid:
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


def _render_legacy_reclassify(procurement_id: int, active_key: str) -> None:
    """Fast reclassification for legacy negatives — no advanced form required."""
    from src.services.db_bootstrap import connect_databases
    from src.services.expert_annotation_service import load_model_assessment_for_annotation
    from src.ui.components.analytics_v2.annotation_card import _persist, scope_decision_key
    from src.ui.components.analytics_v2.annotation_queue import GO_NEXT_FROM_KEY, GO_NEXT_KEY

    st.info("Старая метка: **Неинтересная**. Новая классификация (этап 1 — объект / тип / категории):")
    c1, c2, c3 = st.columns(3)
    created_by = st.session_state.get("user_name") or "expert"
    _, _, crm_db, _ = connect_databases()
    assessment = load_model_assessment_for_annotation(procurement_id, crm_db)
    if c1.button("Вне товарных категорий", key=f"legacy_out_{procurement_id}", use_container_width=True):
        st.session_state[scope_decision_key(procurement_id)] = "NO"
        st.session_state[active_key] = procurement_id
        return
    if c2.button("Не относится только по другой причине", key=f"legacy_other_{procurement_id}", use_container_width=True):
        payload = build_uncertain_payload(
            assessment=assessment,
            created_by=created_by,
            comment="LEGACY_OTHER_REASON_NOT_CATEGORY",
        )
        _persist(procurement_id, payload, assessment, created_by, crm_db, save_and_next=True)
        return
    if c3.button("Не уверен", key=f"legacy_unsure_{procurement_id}", use_container_width=True):
        st.session_state[scope_decision_key(procurement_id)] = "UNCERTAIN"
        st.session_state[active_key] = procurement_id
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
    """Staged expert surface: object → procurement mode → category gate."""
    from src.ui.components.analytics_v2.annotation_card import scope_decision_key
    from src.ui.components.analytics_v2.staged_annotation_ui import render_source_contour_banner

    key = scope_decision_key(procurement_id)
    # Restore persisted stage-1 decision into session for display continuity.
    if not st.session_state.get(key) and state.get("expert_category_scope"):
        mapping = {IN_CATEGORY: "YES", OUT_OF_CATEGORY: "NO", UNCERTAIN: "UNCERTAIN"}
        st.session_state[key] = mapping.get(state["expert_category_scope"])

    st.markdown("---")
    st.markdown("##### 👤 ЭКСПЕРТНАЯ РАЗМЕТКА")
    render_source_contour_banner((card or {}).get("source_table"))

    if state.get("is_legacy_negative") and not state.get("is_category_reviewed"):
        _render_legacy_reclassify(procurement_id, active_key)
        if st.session_state.get(key) and st.session_state.get(active_key) == procurement_id:
            _render_expensive_section(procurement_id, "Первое решение")
        return

    st.caption("Обычный путь: title + ОКПД2 + контур источника. Документы не обязательны.")
    is_active = st.session_state.get(active_key) == procurement_id
    if state.get("is_staged_complete") and not is_active:
        if st.button("Изменить разметку", key=f"edit_staged_{procurement_id}"):
            st.session_state[active_key] = procurement_id
            st.rerun()
        return
    if not is_active:
        if st.button("Разметить →", key=f"open_staged_{procurement_id}", type="primary"):
            st.session_state[active_key] = procurement_id
            st.rerun()
        return
    _render_expensive_section(procurement_id, "Первое решение")
