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
from src.services.commercial_routing_v3.research_ui_projection import (
    ResearchUiProjection,
    load_research_ui_projection,
)
from src.ui.components.analytics_v2.card_trust import fmt_date, fmt_price

SECTIONS = ("Обзор", "Модель / Категории", "Документы", "История", "Экспертная разметка")
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

RESEARCH_FILTERS = (
    ("ALL", "Все"),
    ("EVIDENCE_FOUND", "Есть находки"),
    ("NO_EVIDENCE", "Нет подтверждений"),
    ("RESEARCHING", "В работе"),
    ("PARTIAL", "Частично"),
    ("FAILED", "Ошибка"),
    ("WAITING_RESEARCH", "Не исследовано"),
)

AI_LABELS = {"ASSESSED": "🤖 AI оценено", "UNASSESSED": "🤖 AI не оценено",
             "INCOMPLETE": "⚠ AI оценка неполная", "FAILED": "❌ Ошибка AI"}
BUSINESS_LABELS = {"IN_PROFILE": "🟢 В профиле", "OUT_OF_PROFILE": "⚪ AI: вне профиля"}
MEDAL_LABELS = {"GOLD": "🥇 GOLD", "SILVER": "🥈 SILVER", "BRONZE": "🥉 BRONZE", "WOOD": "🪵 WOOD"}
MEDAL_FILTERS = (GOLD, SILVER, BRONZE, WOOD)


def _activate_inline(active_key: str, procurement_id: int) -> None:
    st.session_state[active_key] = procurement_id


def _show_documents_tab(active_key: str, procurement_id: int, file_count: int) -> None:
    st.session_state[active_key] = procurement_id
    st.session_state[f"inline_card_tab_{procurement_id}"] = f"Документы · {file_count}"


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


def _research_chips(proj: ResearchUiProjection | None, file_count: int) -> list[str]:
    if not proj:
        return [f"🔬 Документы: {file_count}"] if file_count > 0 else ["○ Исследование не начато"]

    st_val = proj.research_state
    if st_val == "EVIDENCE_FOUND":
        res = [f"🔬 Исследовано {proj.documents_researched or proj.documents_total}/{proj.documents_total}"]
        if proj.documents_with_evidence > 0:
            res.append(f"✅ {proj.documents_with_evidence} док. с находками")
        if proj.evidence_count > 0:
            res.append(f"🎯 {proj.evidence_count} подтверждений")
        return res
    elif st_val == "NO_EVIDENCE":
        return [
            f"🔬 Исследовано {proj.documents_total}/{proj.documents_total}",
            "○ Подтверждений не найдено",
        ]
    elif st_val == "RESEARCHING":
        rem = proj.documents_total - proj.documents_researched
        return [
            f"⏳ Исследование {proj.documents_researched}/{proj.documents_total}",
            f"Осталось: {rem}",
        ]
    elif st_val == "PARTIAL":
        return [
            f"⚠ Исследовано {proj.documents_researched}/{proj.documents_total}",
            f"{proj.documents_unknown} не удалось исследовать",
        ]
    elif st_val == "FAILED":
        return ["❌ Ошибка исследования"]
    elif st_val == "PROJECTION_ERROR":
        return ["⚠ Ошибка базы исследования"]
    else:
        return ["○ Исследование не начато"]


def _render_structured_result(state: dict) -> None:
    summary = staged_card_summary(state.get("payload"))
    if summary["status"] == "UNREVIEWED":
        st.caption("👤 Не проверено")
        return
    title = "👤 Проверено" if summary["status"] == "REVIEWED" else "👤 Частично проверено"
    st.markdown(f"**{title}**")
    for label, value in summary["lines"]:
        st.markdown(f"{label}: **{escape(str(value))}**", unsafe_allow_html=True)


def _render_research_result_block(
    card: dict,
    proj: ResearchUiProjection | None,
    active_key: str,
) -> None:
    """Render explicit factual research result section on main card."""
    pid = card["id"]
    file_count = card.get("file_count") or 0

    st.markdown("---")
    st.markdown("##### 🔎 РЕЗУЛЬТАТ ИССЛЕДОВАНИЯ")

    if not proj or proj.research_state == "WAITING_RESEARCH":
        st.caption("○ Исследование закупки еще не начато")
        return

    st_val = proj.research_state

    if st_val == "EVIDENCE_FOUND":
        st.success(
            f"✅ **Найдены подтверждения по нашим товарным категориям**  \n"
            f"{proj.documents_researched or proj.documents_total} из {proj.documents_total} документов обработано"
        )
        if proj.category_names:
            st.markdown(f"**Категории:** {', '.join(proj.category_names)}")
        if proj.top_matched_terms:
            st.markdown(f"**Найденные термины:** {', '.join(proj.top_matched_terms)}")

        c1, c2 = st.columns(2)
        c1.markdown(f"📄 **Документов с находками:** {proj.documents_with_evidence}")
        c2.markdown(f"🎯 **Подтверждений:** {proj.evidence_count}")

        if st.button("Показать находки в документах →", key=f"show_findings_{pid}", type="primary"):
            _show_documents_tab(active_key, pid, file_count)
            st.rerun()

    elif st_val == "NO_EVIDENCE":
        st.info(
            f"○ **Исследование завершено**  \n"
            f"{proj.documents_total} из {proj.documents_total} документов обработано  \n"
            f"Подтверждений по нашим товарным категориям не найдено."
        )

    elif st_val == "RESEARCHING":
        rem = proj.documents_total - proj.documents_researched
        st.warning(
            f"⏳ **Исследование выполняется**  \n"
            f"{proj.documents_researched} из {proj.documents_total} документов обработано (осталось {rem})  \n"
            f"Уже найдено подтверждений: {proj.evidence_count}"
        )
        if proj.evidence_count > 0:
            if st.button("Показать первые находки в документах →", key=f"show_findings_{pid}"):
                _show_documents_tab(active_key, pid, file_count)
                st.rerun()

    elif st_val == "PARTIAL":
        st.warning(
            f"⚠ **Результат исследования частичный**  \n"
            f"{proj.documents_researched} из {proj.documents_total} документов исследовано, "
            f"{proj.documents_unknown} не удалось надежно обработать.  \n"
            f"Найдено подтверждений: {proj.evidence_count}"
        )
        if proj.evidence_count > 0:
            if st.button("Показать находки в документах →", key=f"show_findings_{pid}"):
                _show_documents_tab(active_key, pid, file_count)
                st.rerun()

    elif st_val == "FAILED":
        st.error("❌ Ошибка при проведении исследования закупки")
    elif st_val == "PROJECTION_ERROR":
        st.error(f"⚠ **Не удалось получить состояние исследования**  \n`{escape(str(proj.error_detail or 'DB authority failure'))}`")


def _summary(
    card: dict,
    stage: str,
    effective: Any,
    state: dict,
    published: bool,
    proj: ResearchUiProjection | None = None,
) -> None:
    amount, amount_label = _amount(card, stage)
    deadline, deadline_label = _deadline(card, stage)
    medal = _clean(getattr(effective, "best_candidate_level", None) if effective else None)
    business = _clean(getattr(effective, "business_relevance", None) if effective else None)
    ai = _clean(getattr(effective, "ai_status", None) if effective else None) or "UNASSESSED"

    r_chips = _research_chips(proj, card.get("file_count") or 0)
    chips = [
        *r_chips,
        MEDAL_LABELS.get(medal, medal) if medal else None,
        *_human_chips(state),
        AI_LABELS.get(ai, f"🤖 {ai}"),
        BUSINESS_LABELS.get(business) if business else None,
        "✓ Опубликовано в CRM" if published else "Не опубликовано менеджерам",
    ]
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


def _filter_matches(
    state: dict,
    selected_state: str,
    proj: ResearchUiProjection | None = None,
    selected_research: str = "ALL",
    selected_category: str = "ALL",
) -> bool:
    # 1. Expert filter match
    if selected_state != "ALL":
        if selected_state == UNREVIEWED and state.get("is_staged_complete"):
            return False
        if selected_state == REVIEWED and not state.get("is_staged_complete"):
            return False
        if selected_state == IN_CATEGORY and state.get("expert_category_scope") != IN_CATEGORY:
            return False
        if selected_state == OUT_OF_CATEGORY and state.get("expert_category_scope") != OUT_OF_CATEGORY:
            return False
        if selected_state == UNCERTAIN and (state.get("expert_category_scope") != UNCERTAIN and state.get("expert_commercial_entry") != "UNCERTAIN"):
            return False
        if selected_state == COMMERCIAL and state.get("expert_commercial_entry") != COMMERCIAL:
            return False
        if selected_state == NON_COMMERCIAL and state.get("expert_commercial_entry") != NON_COMMERCIAL:
            return False
        if selected_state in MEDAL_FILTERS and state.get("expert_medal") != selected_state:
            return False
        if selected_state == LEGACY_NOT_INTERESTING and not state.get("is_legacy_negative"):
            return False

    # 2. Research filter match
    if selected_research != "ALL":
        r_state = proj.research_state if proj else "WAITING_RESEARCH"
        if r_state != selected_research:
            return False

    # 3. Category filter match
    if selected_category != "ALL":
        c_names = proj.category_names if proj else []
        c_codes = proj.category_codes if proj else []
        if selected_category not in c_names and selected_category not in c_codes:
            return False

    return True


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
    projections: dict[int, ResearchUiProjection] | None = None,
    render_research_controls: bool = True,
) -> str:
    from src.services.annotation_queue_service import batch_publication_visibility
    from src.services.db_bootstrap import connect_databases

    _, _, crm_db, _ = connect_databases()
    all_ids = workset_ids or [card["id"] for card in cards]
    all_states = annotation_states or load_current_annotation_states(all_ids, crm_db)
    page_states = {card["id"]: all_states[card["id"]] for card in cards}
    publication = batch_publication_visibility(crm_db, [card["id"] for card in cards])

    if projections is None:
        projections = load_research_ui_projection([card["id"] for card in cards], crm_db)

    if render_research_controls:
        selected_state = selected_annotation_filter or render_review_filter(all_states, session_key)
        selected_research, selected_category = render_research_filters(projections, session_key)
        visible = [
            card for card in cards
            if _filter_matches(
                page_states[card["id"]],
                selected_state,
                projections.get(card["id"]),
                selected_research,
                selected_category,
            )
        ]
    else:
        visible = cards

    active_key = f"active_inline_{session_key}"
    focused = st.session_state.get(session_key)
    if focused in [card["id"] for card in visible]:
        st.session_state[active_key] = focused
        st.session_state[f"inline_card_tab_{focused}"] = "Экспертная разметка"

    for card in visible:
        pid = card["id"]
        proj = projections.get(pid)
        with st.container(border=True):
            _summary(card, stage, (effective_map or {}).get(pid), page_states[pid], publication.get(pid, False), proj=proj)
            _source_actions(card)
            _render_research_result_block(card, proj, active_key)
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
    labels = [f"{label} · {counts[key]}" for key, label in FILTERS]
    selected_label = st.pills(
        "Эксперт",
        labels,
        default=labels[0],
        key=f"annotation_state_filter_{session_key}",
        on_change=on_change,
    )
    return FILTERS[labels.index(selected_label)][0]


def render_research_filters(
    projections: dict[int, ResearchUiProjection],
    session_key: str,
    *,
    on_change: Any = None,
) -> tuple[str, str]:
    """Render research state and category filters with dynamic counts."""
    # Count research states across projections
    r_counts: dict[str, int] = {key: 0 for key, _ in RESEARCH_FILTERS}
    r_counts["ALL"] = len(projections)

    # Collect category counts
    cat_counts: dict[str, int] = {}

    for proj in projections.values():
        st_val = proj.research_state
        if st_val in r_counts:
            r_counts[st_val] += 1

        for c_name in proj.category_names:
            cat_counts[c_name] = cat_counts.get(c_name, 0) + 1

    r_labels = [f"{label} · {r_counts[key]}" for key, label in RESEARCH_FILTERS]
    key_r = f"research_state_filter_{session_key}"
    prev_key_r = f"prev_{key_r}"

    selected_r_label = st.pills(
        "Исследование",
        r_labels,
        default=r_labels[0],
        key=key_r,
        on_change=on_change,
    )
    if st.session_state.get(prev_key_r) != selected_r_label:
        st.session_state[prev_key_r] = selected_r_label
        if callable(on_change):
            on_change()

    selected_research = RESEARCH_FILTERS[r_labels.index(selected_r_label)][0]

    # Category filter dropdown
    cat_options = ["Все"] + [f"{c_name} · {count}" for c_name, count in sorted(cat_counts.items())]
    if len(cat_options) > 1:
        key_c = f"research_category_filter_{session_key}"
        prev_key_c = f"prev_{key_c}"
        selected_cat_opt = st.selectbox(
            "Найденная категория",
            cat_options,
            key=key_c,
            on_change=on_change,
        )
        if st.session_state.get(prev_key_c) != selected_cat_opt:
            st.session_state[prev_key_c] = selected_cat_opt
            if callable(on_change):
                on_change()
        selected_category = selected_cat_opt.split(" · ")[0] if selected_cat_opt != "Все" else "ALL"
    else:
        selected_category = "ALL"

    return selected_research, selected_category


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
