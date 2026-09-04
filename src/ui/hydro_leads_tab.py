"""Primary Hydro Leads work queue; reads only the canonical CRM repository."""
from __future__ import annotations
import streamlit as st
from src.services.hydro.card_projection import HydroLeadCardDTO
from src.services.hydro.lead_repository import HydroLeadRepository

def _object_caption(card: HydroLeadCardDTO) -> str:
    if not card.top_objects: return "Объекты не загружены"
    obj = card.top_objects[0]
    return " · ".join(x for x in (obj.address, obj.cadastral_number, f"{obj.area_total:g} м²" if obj.area_total else None) if x) or "Факты объекта уточняются"

def render_lead_detail(repo: HydroLeadRepository, lead_id: int | str) -> None:
    card = repo.get_lead(lead_id)
    if not card: st.warning("Лид не найден."); return
    st.subheader(card.company_name or "УК НЕ ОПРЕДЕЛЕНА")
    st.caption(f"{card.lead_kind} · {card.state} · {card.object_count} объектов · источник: {card.source_health}")
    if card.next_task_label: st.info(f"Следующее действие: {card.next_task_label}")
    st.write(f"Потенциал объекта: {card.potential.grade} ({card.potential.score}) · Готовность лида: {card.readiness.grade} ({card.readiness.score})")
    for obj in card.top_objects:
        with st.container(border=True):
            st.markdown(f"**{obj.address or 'Адрес не указан'}** · {obj.cadastral_number or 'кадастр не указан'}")
            st.caption(f"Площадь: {obj.area_total or '—'} · Подземных этажей: {obj.floors_underground or '—'} · Потенциал: {obj.potential.grade} ({obj.potential.score})")
            if obj.missing_facts: st.warning("Неизвестно: " + ", ".join(obj.missing_facts))

def render_hydro_leads_tab(crm_db) -> None:
    repo = HydroLeadRepository(crm_db) if crm_db else None
    if repo is None:
        st.info("Карточки Hydro недоступны: canonical CRM DB не подключена."); return
    st.header("🔥 Лиды")
    st.caption("Рабочая очередь Hydro: canonical CRM snapshot, без прямого обращения к источнику NSPD.")
    with st.sidebar:
        kind = st.selectbox("Тип лида", ["Все", "COMPANY_CONTOUR", "STANDALONE_OBJECT"], key="hydro_lead_kind")
        state = st.selectbox("Состояние", ["Все", "NEW", "IN_PROGRESS", "MERGED"], key="hydro_lead_state")
        resolved = st.selectbox("УК", ["Все", "Определена", "Не определена"], key="hydro_company_resolved")
        text = st.text_input("Поиск", key="hydro_lead_search")
    filters = {"lead_kind": None if kind == "Все" else kind, "hydro_state": None if state == "Все" else state,
               "company_resolved": None if resolved == "Все" else resolved == "Определена", "text": text or None}
    cards = repo.list_leads(filters=filters, limit=100)
    if not repo.schema_available:
        st.warning("Карточки Hydro пока недоступны: canonical Hydro schema не развернута в CRM DB. Legacy view сохранён ниже."); return
    if not cards: st.info("Лидов по выбранным условиям нет."); return
    for card in cards:
        with st.container(border=True):
            title = card.company_name if card.company_resolved else "УК НЕ ОПРЕДЕЛЕНА"
            st.subheader(title)
            st.caption(f"{card.lead_kind} · {card.state} · {_object_caption(card)}")
            st.write(f"Потенциал: {card.potential.grade} ({card.potential.score}) · Готовность: {card.readiness.grade} ({card.readiness.score}) · источник: {card.source_health}")
            if card.next_task_label: st.info(f"Следующее действие: {card.next_task_label}")
            if st.button("Открыть все объекты", key=f"hydro_lead_{card.lead_id}"): st.session_state["hydro_detail_lead_id"] = card.lead_id
    detail_id = st.session_state.get("hydro_detail_lead_id")
    if detail_id is not None: render_lead_detail(repo, detail_id)
