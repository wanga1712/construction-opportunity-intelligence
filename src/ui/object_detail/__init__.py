"""Salesforce-style object detail page."""
from __future__ import annotations

import html
from typing import Callable

import streamlit as st

from modules.crm.analytics.object_classifier import segment_label
from modules.crm.repositories.tender_registry_constants import registry_label
from src.constants.object_quality import TIER_LABELS
from src.constants.product_groups import PRODUCT_GROUP_OPTIONS
from src.services.docs_match_preview import (
    apply_match_previews,
    confirmed_product_groups,
    other_product_groups,
    preview_line_for_group,
)
from src.services.object_ai_classification_store import apply_ai_classifications
from src.services.object_ai_scores import apply_object_ai_scores
from src.services.object_category_labels import apply_object_category_labels
from src.services.object_detail_loader import load_object_detail
from src.services.object_interest_service import mark_object_not_interesting
from src.services.object_leads_bridge import object_lead_status, upsert_object_lead
from src.services.objects_service import ObjectsService
from src.ui.object_card_format import fmt_date, is_awarded_registry

from .ai_tab import (
    _can_dismiss,
    _render_ai_shadow_v2,
    _render_category_label,
    _render_document_upload,
    _render_procurement_chat,
)
from .docs_tab import _render_docs_tab
from .formatters import _METRIC_ICONS, _SEGMENT_ICONS, _fmt_price
from .layout import _compact_metrics, _section_title, _sf_fields
from .matches_tab import _render_matches_tab


def render_object_detail(
    objects_service: ObjectsService,
    object_key: str,
    on_back: Callable[[], None],
) -> None:
    """Детальная страница объекта."""
    item = objects_service.get_item_by_key(object_key)
    if not item:
        st.warning("Объект не найден.")
        if st.button("← Назад к списку", key="object_detail_not_found_back"):
            on_back()
        return
    with st.spinner("Загрузка из БД…"):
        detail = load_object_detail(
            item, tender_db=objects_service.tender_db, radar_db=objects_service.radar_db,
        )
    apply_object_category_labels([detail.item])
    apply_object_ai_scores([detail.item])
    apply_ai_classifications([detail.item], objects_service.crm_db)
    apply_match_previews(objects_service.tender_db, [detail.item])
    item, awarded = detail.item, is_awarded_registry(detail.item.registry_type)
    active_product_group = st.session_state.get("object_detail_product_group")
    confirmed_groups = confirmed_product_groups(item)
    if active_product_group and active_product_group not in confirmed_groups:
        st.session_state.pop("object_detail_product_group", None)
        active_product_group = None
    dismiss_key, dismiss_err_key = f"dismiss_confirm_{object_key}", f"dismiss_err_{object_key}"

    hdr_left, hdr_right = st.columns([4, 1])
    with hdr_left:
        seg_ico = _SEGMENT_ICONS.get(item.segment or "", "🏗️")
        st.markdown(
            f'<p class="sf-record-title"><span class="sf-record-ico">{seg_ico}</span>'
            f'{html.escape(item.name or "—")}</p>', unsafe_allow_html=True,
        )
        badges = []
        if item.status:
            badges.append(("📑", item.status))
        elif item.registry_type:
            badges.append(("📑", registry_label(item.registry_type)))
        if item.quality_tier:
            badges.append(("📊", TIER_LABELS.get(item.quality_tier, item.quality_tier)))
        if badges:
            st.markdown(" ".join(
                f'<span class="sf-badge"><span class="sf-ico">{ico}</span>{html.escape(text)}</span>'
                for ico, text in badges
            ), unsafe_allow_html=True)
        if detail.tender_link:
            st.markdown(f"🔗 [Открыть на площадке]({detail.tender_link})")
        if item.address:
            st.caption(f"📍 {item.address}")
        elif item.region:
            st.caption(f"📍 {item.region}")
        if confirmed_groups:
            labels = dict(PRODUCT_GROUP_OPTIONS)
            if active_product_group:
                st.caption(
                    f"🎯 Направление: {labels.get(active_product_group, active_product_group)} · "
                    f"{preview_line_for_group(item, active_product_group)}"
                )
            cross = other_product_groups(item, active_product_group)
            if cross:
                st.caption(
                    "Также релевантно: "
                    + ", ".join(label for _code, label in cross)
                )

    with hdr_right:
        if st.button("← К радару объектов", key="object_detail_back", use_container_width=True):
            on_back()
            return
        lead_state = object_lead_status(objects_service.crm_db, object_key)
        if lead_state:
            st.caption(f"В CRM: lead #{lead_state.get('id')} · score {lead_state.get('score')}")
        if st.button("Взять в работу", key=f"object_take_work_{object_key}", use_container_width=True, type="primary"):
            try:
                result = upsert_object_lead(objects_service.crm_db, item, mark_taken=True)
                st.toast("Объект связан с CRM и отмечен как взятый в работу" if result == "created" else "CRM-состояние объекта обновлено", icon="✅")
                st.rerun()
            except Exception as exc:
                st.error(f"Не удалось взять объект в работу: {exc}")
        if _can_dismiss(item):
            if st.button("👎 Не интересно", key="object_dismiss_btn", use_container_width=True, type="secondary"):
                st.session_state[dismiss_key] = True
            if st.session_state.get(dismiss_key):
                st.warning("Скрыть объект из списка? Статус сохранится в БД.")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Да, скрыть", key="object_dismiss_yes", use_container_width=True):
                        ok, msg = mark_object_not_interesting(
                            tender_db=objects_service.tender_db, crm_db=objects_service.crm_db,
                            tender_id=item.tender_id, registry_type=item.registry_type,
                            object_key=object_key, objects_service=objects_service,
                        )
                        st.session_state.pop(dismiss_key, None)
                        if ok:
                            st.session_state.pop(dismiss_err_key, None)
                            st.toast(msg, icon="✅")
                            on_back()
                        else:
                            st.session_state[dismiss_err_key] = msg
                            st.rerun()
                with c2:
                    if st.button("Отмена", key="object_dismiss_no", use_container_width=True):
                        st.session_state.pop(dismiss_key, None)
                        st.rerun()
    dismiss_err = st.session_state.pop(dismiss_err_key, None)
    if dismiss_err:
        st.error(dismiss_err)

    seg_text = segment_label(item.segment) if item.segment else "—"
    metric_icons = dict(_METRIC_ICONS)
    if item.segment:
        metric_icons["Сегмент"] = _SEGMENT_ICONS.get(item.segment, "🏷️")
    _compact_metrics([
        ("Совпадений", str(item.doc_matches or 0)),
        ("Файлов", str(item.matched_files or len(detail.match_files))),
        ("НМЦ", _fmt_price(detail.initial_price)),
        ("Итог", _fmt_price(detail.final_price)),
        ("AI", str(item.ai_priority_score or "—")),
        ("Сегмент", seg_text),
    ], cols=6, icons=metric_icons)
    if item.ai_priority_reason:
        st.caption(f"AI ранжирование: {item.ai_priority_reason}"
                   + (f" · шанс поставки: {item.ai_delivery_chance}" if item.ai_delivery_chance else "")
                   + (f" · объём: {item.ai_volume_signal}" if item.ai_volume_signal else ""))
    if item.ai_primary_class or item.ai_work_type or item.ai_project_stage:
        tags = ", ".join(item.ai_infrastructure_tags or [])
        st.caption("AI классификация: " + " → ".join(x for x in [item.ai_primary_class, item.ai_subcategory, item.ai_object_type] if x)
                   + (f" · работы: {item.ai_work_type}" if item.ai_work_type else "")
                   + (f" · стадия: {item.ai_project_stage}" if item.ai_project_stage else "")
                   + (f" · теги: {tags}" if tags else ""))

    st.markdown('<div class="object-detail-body">', unsafe_allow_html=True)
    tab_overview, tab_matches, tab_dates, tab_docs, tab_ai_chat, tab_extra = st.tabs([
        "📊 Обзор", "🎯 Совпадения", "📅 Даты и цены", "📎 Документация",
        "🤖 AI и чат", "🔍 Экспертиза / NashDom",
    ])
    with tab_overview:
        with st.container(border=True):
            _section_title("Закупка")
            _sf_fields([
                ("Реестр", item.status or registry_label(item.registry_type or "")),
                ("№ закупки", detail.contract_number or item.contract_number),
                ("Регион поставки", detail.delivery_region), ("ОКПД", detail.okpd_code),
                ("Описание ОКПД", detail.okpd_name), ("Площадка", detail.platform_name),
                ("Ссылка площадки", detail.platform_url),
            ])
        with st.container(border=True):
            _section_title("Участники")
            organizer = item.customer_name or ""
            if organizer and item.customer_inn:
                organizer = f"{organizer} (ИНН {item.customer_inn})"
            winner = item.contractor_name or ""
            if winner and item.contractor_inn:
                winner = f"{winner} (ИНН {item.contractor_inn})"
            fields = [("Балансодержатель", item.balance_holder)]
            if organizer and organizer != item.balance_holder:
                fields.append(("Организатор торгов", organizer))
            if awarded and winner:
                fields.append(("Подрядчик / победитель", winner))
            if item.expertise_planner:
                fields.append(("Проектировщик", item.expertise_planner))
            if item.expertise_technical_customer:
                fields.append(("Технический заказчик", item.expertise_technical_customer))
            if item.expertise_developer:
                fields.append(("Застройщик / баланс по экспертизе", item.expertise_developer))
            _sf_fields(fields)
    with tab_matches:
        _render_matches_tab(detail, object_key, active_product_group=active_product_group)
    with tab_dates:
        with st.container(border=True):
            _section_title("Торги")
            _compact_metrics([("Начало", fmt_date(item.start_date)), ("Окончание", fmt_date(item.end_date))], cols=2)
        with st.container(border=True):
            _section_title("Поставка / исполнение")
            _compact_metrics([("Начало", fmt_date(item.delivery_start_date)), ("Окончание", fmt_date(item.delivery_end_date))], cols=2)
        with st.container(border=True):
            _section_title("Цены")
            _compact_metrics([("НМЦ", _fmt_price(detail.initial_price)), ("Итоговая", _fmt_price(detail.final_price))], cols=2)
    with tab_docs:
        _render_docs_tab(detail, object_key)
    with tab_ai_chat:
        _render_procurement_chat(detail)
        _render_ai_shadow_v2(detail)
        _render_category_label(detail, objects_service)
        _render_document_upload(detail)
    with tab_extra:
        with st.container(border=True):
            _section_title("Экспертиза")
            if detail.expertise_rows:
                for row in detail.expertise_rows:
                    st.markdown(f"🧾 **{html.escape(row.get('expertise_number') or '—')}** · {html.escape(row.get('expertise_result_type') or '')}")
                    if row.get("expertise_date"):
                        st.caption(str(row["expertise_date"])[:10])
            elif item.expertise_number:
                st.markdown(f"**{html.escape(item.expertise_number)}**")
            else:
                st.caption("Данные экспертизы не привязаны.")
        with st.container(border=True):
            _section_title("NashDom")
            if detail.nashdom_rows:
                for row in detail.nashdom_rows:
                    st.markdown(f"🏗️ **{html.escape(row.get('name') or '—')}**")
                    if row.get("address_text"):
                        st.caption(row["address_text"])
                    st.caption(f"{row.get('status_name') or '—'} · ПД {row.get('pd_number') or '—'}")
            elif item.domrf_object_id:
                st.caption(f"NashDom ID: {item.domrf_object_id}")
            else:
                st.caption("Объект NashDom не привязан.")
    st.markdown("</div>", unsafe_allow_html=True)


__all__ = ["render_object_detail"]
