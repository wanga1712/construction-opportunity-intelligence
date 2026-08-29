"""Presentation sections for the dedicated annotation workbench card."""
from __future__ import annotations

from html import escape
import streamlit as st

from src.services.commercial_routing_v3.model_ui_projection import business_view_from_assessment, model_view_from_assessment
from src.ui.components.analytics_v2.card_trust import fmt_price


def render_workbench_header(header: dict, procurement_id: int, lifecycle: str, publication_visible: bool) -> None:
    st.markdown(f"## {header.get('title') or 'Закупка без названия'}")
    amount, deadline, law = st.columns(3)
    amount.metric(header.get("display_amount_label") or "Сумма", fmt_price(header.get("display_amount")))
    deadline.metric(header.get("deadline_label") or "Срок", str(header.get("deadline") or "—"))
    law.metric("Закон / источник", header.get("law") or "—")
    if header.get("lifecycle") == "AWARDED" and header.get("initial_price") is not None:
        st.caption(f"Начальная цена / НМЦК: {fmt_price(header.get('initial_price'))}")
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"**Заказчик**  \n{header.get('customer') or '—'}")
    c2.markdown(f"**Регион**  \n{header.get('region') or '—'}")
    c3.markdown(f"**Номер**  \n`{header.get('procurement_number') or procurement_id}`")
    actions = st.columns(2)
    if header.get("procurement_url"):
        actions[0].link_button("🔗 Открыть закупку", header["procurement_url"], type="primary")
    if header.get("contract_url"):
        actions[1].link_button("📄 Открыть контракт", header["contract_url"])
        actions[1].caption(f"Источник: {header.get('contract_url_provenance')}")
    st.caption(f"lifecycle={lifecycle} · publication={'visible' if publication_visible else 'hidden (annotation доступна)'} · CRM id={procurement_id}")


def render_overview(header: dict, assessment: dict | None, existing: dict | None) -> None:
    model = model_view_from_assessment(assessment)
    business = business_view_from_assessment(assessment)
    payload = (existing or {}).get("payload") or {}
    s, m, b, e = st.columns(4)
    with s:
        st.markdown("#### 📄 SOURCE FACTS")
        st.markdown(f"**Заказчик:** {header.get('customer') or '—'}")
        st.markdown(f"**Подрядчик:** {header.get('contractor') or 'нет подтверждённых данных'}")
        st.markdown(f"**ОКПД:** `{header.get('okpd_code') or '—'}`")
        st.markdown(f"**Создано:** {header.get('crm_created_at') or '—'}")
    with m:
        st.markdown("#### 🤖 MODEL")
        if model.get("provenance") == "UNKNOWN_LEGACY":
            st.warning("Legacy: RAW модели не сохранён")
        st.markdown(f"**Объект:** {model.get('object_type') or '—'} / {model.get('object_subtype') or '—'}")
        st.markdown(f"**Стадия:** {model.get('work_stage') or '—'}")
        st.markdown(f"**Confidence:** {model.get('overall_confidence') if model.get('overall_confidence') is not None else '—'}")
    with b:
        st.markdown("#### ⚙️ BUSINESS RULE")
        st.markdown(f"**Route:** `{business.get('route_profile') or '—'}`")
        st.markdown(f"**Scope:** `{business.get('business_scope_status') or '—'}`")
        st.markdown(f"**Medal / score:** {business.get('effective_medal') or business.get('business_candidate_medal') or '—'} / {business.get('business_candidate_score') if business.get('business_candidate_score') is not None else '—'}")
        st.markdown(f"**Окно:** до {header.get('end_date') or '—'}")
    with e:
        st.markdown("#### 👤 EXPERT")
        if not existing:
            st.info("Экспертная версия ещё не сохранена")
        st.markdown(f"**Вердикт:** `{payload.get('expert_verdict') or '—'}`")
        st.markdown(f"**Объект:** {payload.get('expert_object_type') or '—'} / {payload.get('expert_object_subtype') or '—'}")
        st.markdown(f"**Стадия:** {payload.get('expert_work_stage') or '—'}")


def render_documents(
    procurement_id: int,
    rows: list[dict],
    priority_state: dict[str, str],
    orphan_observations: list[dict] | None = None,
) -> None:
    st.markdown("### 📎 Документы закупки")
    if not rows:
        st.info("Источник не вернул документов для этой закупки. Исследование автоматически не запускается.")
        return

    for idx, row in enumerate(rows, 1):
        key = str(row.get("document_url") or row.get("source_document_id") or idx)
        research_ev = row.get("research_evidence") or []

        with st.container(border=True):
            left, right = st.columns([4, 2])
            left.markdown(f"**{idx}. {row.get('document_name') or 'Документ без имени'}**")
            left.caption(
                f"source_document_id=`{row.get('source_document_id') or '—'}` · "
                f"тип=`{row.get('document_type') or '—'}` · источник=`{row.get('link_source') or '—'}`"
            )
            if int(row.get("source_row_count") or 1) > 1:
                left.caption(f"Один физический файл представлен {row['source_row_count']} строками/версиями источника")
            
            if row.get("document_url"):
                left.link_button("Открыть / скачать документ", row["document_url"])

            state = row.get("observation_state") or "UNOBSERVED"

            # Render explicit Research Result for this document immediately under download button
            if research_ev:
                left.success(f"✅ В этом документе найдено: {len(research_ev)} подтверждений")
                cat_names = sorted(list({e.get("category_name") for e in research_ev if e.get("category_name")}))
                if cat_names:
                    left.markdown("**Категории:** " + ", ".join(cat_names))
                
                for ev_idx, ev in enumerate(research_ev, 1):
                    term = ev.get("matched_term") or "совпадение"
                    c_name = ev.get("category_name") or ev.get("suggested_category_code") or ""
                    loc = ev.get("friendly_locator") or ""
                    text_snip = ev.get("raw_text") or ""

                    header_line = f"**{ev_idx}. {escape(str(term))}**"
                    if c_name:
                        header_line += f" &nbsp;•&nbsp; *Категория: {escape(str(c_name))}*"
                    if loc:
                        header_line += f" &nbsp;•&nbsp; `{escape(str(loc))}`"

                    left.markdown(header_line, unsafe_allow_html=True)
                    if text_snip:
                        left.markdown(f"> «{escape(str(text_snip[:400]))}»", unsafe_allow_html=True)
            elif state == "OBSERVED_NO_EVIDENCE":
                left.info("○ Исследован · Подтверждений по нашим категориям не найдено")
            elif state in {"DOWNLOAD_FAILED", "PARSE_FAILED", "UNSUPPORTED_FORMAT", "EMPTY_DOCUMENT"}:
                err_labels = {
                    "DOWNLOAD_FAILED": "Ошибка скачивания документа",
                    "PARSE_FAILED": "Ошибка разбора документа",
                    "UNSUPPORTED_FORMAT": "Формат документа не поддерживается",
                    "EMPTY_DOCUMENT": "Пустой документ",
                }
                left.error(f"⚠ {err_labels.get(state, state)}")
            else:
                left.caption("○ Документ ожидает исследования")

            # Legacy observations compatibility rendering
            for observation in row.get("observations") or []:
                categories = observation.get("matched_categories") or []
                mentions = observation.get("product_mentions") or []
                if categories and not research_ev:
                    left.markdown("**Категории (legacy):** " + ", ".join(map(str, categories)))
                if mentions and not research_ev:
                    left.markdown("**Материалы / товары (legacy):** " + ", ".join(map(str, mentions[:8])))

            current = priority_state.get(key, "none")
            selected = right.radio(
                "Приоритет открытия",
                ["none", "first", "second"],
                index=["none", "first", "second"].index(current),
                format_func=lambda value: {"none": "Не отмечен", "first": "Открывал бы в первую очередь", "second": "Открывал бы во вторую очередь"}[value],
                key=f"ann_doc_priority_{procurement_id}_{idx}",
            )
            priority_state[key] = selected

    if orphan_observations:
        st.warning(f"Непривязанные наблюдения: {len(orphan_observations)}. Они не прикреплены к случайным документам.")


def render_history(events: list[dict]) -> None:
    st.markdown("### 🕒 Реальная история и provenance")
    if not events:
        st.info("Подтверждённых исторических событий нет.")
        return
    for event in reversed(events):
        at = event["at"].strftime("%d.%m.%Y %H:%M") if hasattr(event["at"], "strftime") else str(event["at"])
        st.markdown(f"**{at} · {event['title']}**  \n{event['detail']}  \n`authority: {event['authority']}`")
        st.divider()
