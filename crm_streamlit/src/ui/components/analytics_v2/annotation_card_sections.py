"""Presentation sections for the dedicated annotation workbench card."""
from __future__ import annotations

import streamlit as st

from src.services.annotation_card_provenance import project_document_rows, source_law
from src.services.commercial_routing_v3.model_ui_projection import business_view_from_assessment, model_view_from_assessment
from src.ui.components.analytics_v2.card_trust import fmt_price, submission_status


def render_workbench_header(header: dict, procurement_id: int, lifecycle: str, publication_visible: bool) -> None:
    status_icon, status_label, _ = submission_status(header.get("award_status", "submission_open"), header.get("end_date"))
    st.markdown(f"## {header.get('auction_name') or 'Закупка без названия'}")
    link = header.get("tender_link")
    if link:
        st.link_button("🔗 Открыть закупку", link, type="primary")
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f"**Номер**  \n`{header.get('contract_number') or procurement_id}`")
    c2.markdown(f"**Источник / закон**  \n`{header.get('source_table') or '—'}` · {source_law(header.get('source_table'))}")
    c3.markdown(f"**Регион / цена**  \n{header.get('delivery_region') or '—'} · {fmt_price(header.get('final_price') or header.get('initial_price'))}")
    c4.markdown(f"**Статус / дедлайн**  \n{status_icon} {status_label} · {header.get('end_date') or '—'}")
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


def render_documents(procurement_id: int, rows: list[dict], priority_state: dict[str, str]) -> None:
    st.markdown("### 📎 Документы для экспертной проверки")
    docs = project_document_rows(rows)
    if not docs:
        st.info("Документные наблюдения для этой закупки не сохранены. Документы не выдумываются и исследование автоматически не запускается.")
        return
    for idx, row in enumerate(docs, 1):
        key = row["document_key"]
        with st.container(border=True):
            left, right = st.columns([4, 2])
            left.markdown(f"**{idx}. {row.get('document_title') or row['file_name']}**")
            left.caption(f"Файл: `{row['file_name']}` · тип: `{row.get('source_document_type') or '—'}` · parse: `{row.get('parse_status') or '—'}`")
            if row.get("source_document_url"):
                left.link_button("Открыть / скачать документ", row["source_document_url"])
            match_label = "✅ найдены" if row["match_found"] else "— не найдены"
            evidence_label = "✅ найдено" if row["evidence_found"] else "— не найдено"
            left.markdown(f"**Matches:** {match_label} · **Evidence:** {evidence_label}")
            if row["category_signals"]:
                left.markdown("**Категорийные сигналы:** " + ", ".join(map(str, row["category_signals"])))
            if row["product_mentions"]:
                left.caption("Упоминания: " + ", ".join(map(str, row["product_mentions"][:8])))
            current = priority_state.get(key, "none")
            selected = right.radio(
                "Приоритет открытия",
                ["none", "first", "second"],
                index=["none", "first", "second"].index(current),
                format_func=lambda value: {"none": "Не отмечен", "first": "Открывал бы в первую очередь", "second": "Открывал бы во вторую очередь"}[value],
                key=f"ann_doc_priority_{procurement_id}_{idx}",
            )
            priority_state[key] = selected


def render_history(events: list[dict]) -> None:
    st.markdown("### 🕒 Реальная история и provenance")
    if not events:
        st.info("Подтверждённых исторических событий нет.")
        return
    for event in reversed(events):
        at = event["at"].strftime("%d.%m.%Y %H:%M") if hasattr(event["at"], "strftime") else str(event["at"])
        st.markdown(f"**{at} · {event['title']}**  \n{event['detail']}  \n`authority: {event['authority']}`")
        st.divider()
