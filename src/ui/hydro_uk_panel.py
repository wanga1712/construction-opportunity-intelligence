"""Карточка УК: параметры приёма, контакты, встречи (канонические таблицы CRM).

Блок «Параметры приёма» отвечает на вопросы менеджера: есть ли сайт УК, как УК
принимает (живая очередь или по записи), какой график и на какой стадии сделка.
Все четыре параметра — поля менеджера: ночной синк их не пишет.

«Контакты УК» и «Встречи» живут в `company_contacts` / `company_activities`.
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Mapping

import streamlit as st

from src.services.hydro import company_repository as cr
from src.services.hydro.company_repository import HydroCompanyRepository
from src.ui import system_health_slds as slds


def _section_title(text: str) -> str:
    return f'<div class="slds-card__title" style="font-size:16px;margin:2px 0 8px 0">{slds.esc(text)}</div>'

MANUAL_BADGE = "Поле менеджера"

SCHEDULE_HINT = "Например: пн 09:00-18:00; вт 10:00-17:00"
STUB_HINT = "Блок-заглушка: данные появятся после первого заполнения менеджером."


def _row(label: str, value_html: str, badge: str = "") -> str:
    right = slds.badge(badge, "info") if badge else ""
    return (
        '<div class="slds-svc"><span>'
        f'<span class="slds-label">{slds.esc(label)}</span>'
        f'<div class="slds-svc__name">{value_html}</div></span>'
        f"<span>{right}</span></div>"
    )


def _params_card(company: Mapping[str, Any]) -> None:
    website = company.get("website")
    site_html = (f'<a href="{slds.esc(website)}" target="_blank" rel="noopener">'
                 f'{slds.esc(website)}</a>') if website else '<span class="slds-empty">не заполнен</span>'
    reception = cr.reception_label(company.get("reception_type"))
    content = "".join((
        _row("Сайт", site_html, MANUAL_BADGE),
        _row("Тип приёма", slds.badge(reception, "ok" if reception == cr.reception_label("daily") else "info"), MANUAL_BADGE),
        _row("График приёма",
             slds.esc(cr.schedule_text(company.get("reception_schedule"))) or '<span class="slds-empty">не заполнен</span>',
             MANUAL_BADGE),
        _row("Стадия", slds.badge(cr.stage_label(company.get("stage")), "info"), MANUAL_BADGE),
    ))
    st.markdown(slds.card("Параметры приёма", content, role="Сайт, приём, график, стадия"),
                unsafe_allow_html=True)


def _params_form(repo: HydroCompanyRepository, company: Mapping[str, Any]) -> None:
    company_id = company["id"]
    with st.expander("✏️ Изменить параметры приёма", expanded=False):
        with st.form(f"hydro_uk_params_{company_id}"):
            left, right = st.columns(2)
            website = left.text_input("Сайт", value=str(company.get("website") or ""),
                                      placeholder="https://uk.example.ru")
            types = ["", *cr.RECEPTION_TYPES]
            current_type = str(company.get("reception_type") or "daily")
            reception_type = right.selectbox(
                "Тип приёма", types,
                index=types.index(current_type) if current_type in types else 1,
                format_func=lambda v: cr.RECEPTION_TYPE_LABELS.get(v, "— не задано —") if v else "— не задано —",
            )
            schedule = left.text_input("График приёма",
                                       value=cr.schedule_text(company.get("reception_schedule")),
                                       placeholder=SCHEDULE_HINT)
            stages = ["", *cr.STAGES]
            current_stage = str(company.get("stage") or "lead")
            stage = right.selectbox(
                "Стадия", stages,
                index=stages.index(current_stage) if current_stage in stages else 1,
                format_func=lambda v: cr.STAGE_LABELS.get(v, "— не задано —") if v else "— не задано —",
            )
            if st.form_submit_button("💾 Сохранить параметры", type="primary"):
                repo.save_params(company_id, {
                    "website": website, "reception_type": reception_type,
                    "reception_schedule": schedule, "stage": stage,
                })
                st.success("Параметры приёма сохранены.")
                st.rerun()


def render_uk_params(repo: HydroCompanyRepository, company: Mapping[str, Any]) -> None:
    _params_card(company)
    _params_form(repo, company)


def render_uk_contacts(repo: HydroCompanyRepository, company_id: int) -> None:
    st.markdown(_section_title("Контакты УК"), unsafe_allow_html=True)
    contacts = repo.list_contacts(company_id)
    if contacts:
        body = "".join(
            _row(item.get("full_name") or "—",
                 slds.esc(" · ".join(filter(None, [
                     item.get("role"), item.get("phone"),
                     item.get("email"), item.get("comment"),
                 ])) or "нет деталей"),
                 "Основной" if item.get("is_primary") else "") 
            for item in contacts
        )
        st.markdown(slds.card(f"Контакты ({len(contacts)})", body), unsafe_allow_html=True)
    else:
        st.markdown(slds.alert_card("Контакты УК не заведены", tone="neutral",
                                    lines=(STUB_HINT,)), unsafe_allow_html=True)
    with st.expander("➕ Добавить контакт", expanded=False):
        with st.form(f"hydro_uk_contact_{company_id}"):
            left, right = st.columns(2)
            full_name = left.text_input("ФИО *", placeholder="Иванов Иван Иванович")
            role = right.text_input("Должность", placeholder="Главный инженер")
            phone = left.text_input("Телефон", placeholder="+7 ...")
            email = right.text_input("E-mail", placeholder="name@uk.ru")
            comment = left.text_input("Комментарий")
            is_primary = right.checkbox("Основной контакт", value=not contacts)
            if st.form_submit_button("💾 Сохранить контакт", type="primary"):
                if not full_name.strip():
                    st.error("Нужно ФИО контакта.")
                elif repo.add_contact(company_id, {
                    "full_name": full_name, "role": role, "phone": phone,
                    "email": email, "comment": comment, "is_primary": is_primary,
                }) is None:
                    st.error("Контакт не сохранён.")
                else:
                    st.success("Контакт добавлен.")
                    st.rerun()


def render_uk_activities(repo: HydroCompanyRepository, company_id: int) -> None:
    st.markdown(_section_title("Встречи"), unsafe_allow_html=True)
    activities = repo.list_activities(company_id)
    if activities:
        body = "".join(
            _row(item.get("title") or cr.ACTIVITY_TYPE_LABELS.get(item.get("activity_type"), "Встреча"),
                 slds.esc(" · ".join(filter(None, [
                     cr.ACTIVITY_TYPE_LABELS.get(item.get("activity_type"), ""),
                     _fmt_moment(item.get("start_time")),
                     cr.ACTIVITY_STATUS_LABELS.get(item.get("status"), ""),
                 ])) or "нет деталей"))
            for item in activities
        )
        st.markdown(slds.card(f"Встречи и касания ({len(activities)})", body), unsafe_allow_html=True)
    else:
        st.markdown(slds.alert_card("Встречи не назначены", tone="neutral",
                                    lines=(STUB_HINT,)), unsafe_allow_html=True)
    with st.expander("➕ Назначить встречу", expanded=False):
        with st.form(f"hydro_uk_meeting_{company_id}"):
            title = st.text_input("Тема", placeholder="Обследование паркингов")
            left, right = st.columns(2)
            kind = left.selectbox("Тип", cr.ACTIVITY_TYPES, index=0,
                                  format_func=lambda v: cr.ACTIVITY_TYPE_LABELS.get(v, v))
            when_date = left.date_input("Дата", value=date.today())
            when_time = right.time_input("Время", value=time(10, 0))
            status = right.selectbox("Статус", tuple(cr.ACTIVITY_STATUS_LABELS), index=0,
                                     format_func=lambda v: cr.ACTIVITY_STATUS_LABELS.get(v, v))
            description = st.text_area("Комментарий")
            if st.form_submit_button("💾 Сохранить встречу", type="primary"):
                repo.add_activity(company_id, {
                    "activity_type": kind, "title": title, "description": description,
                    "start_time": datetime.combine(when_date, when_time), "status": status,
                })
                st.success("Встреча сохранена.")
                st.rerun()


def _fmt_moment(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    return str(value or "")


@st.cache_resource(show_spinner=False)
def _fallback_crm_db() -> Any:
    """Карточка УК может открываться и там, где сервис не передан."""
    try:
        from src.services.db_bootstrap import connect_crm_database

        return connect_crm_database()
    except Exception:  # noqa: BLE001
        return None


def render_uk_crm_panel(crm_db: Any, uk_inn: Any, uk_name: Any) -> None:
    """Найти УК по ИНН, при необходимости завести, и показать блоки CRM."""
    if crm_db is None:
        crm_db = _fallback_crm_db()
    repo = HydroCompanyRepository(crm_db)
    if not repo.schema_available:
        st.info("CRM БД недоступна: параметры приёма, контакты и встречи не показаны.")
        return
    company = repo.get_by_inn(uk_inn)
    if not company:
        stub = {"id": None, "website": None, "reception_type": "daily",
                "reception_schedule": None, "stage": "lead"}
        st.markdown(slds.card("Параметры приёма",
                              _row("Сайт", '<span class="slds-empty">не заполнен</span>', MANUAL_BADGE)
                              + _row("Тип приёма", slds.badge(cr.reception_label("daily"), "ok"), MANUAL_BADGE)
                              + _row("График приёма", '<span class="slds-empty">не заполнен</span>', MANUAL_BADGE)
                              + _row("Стадия", slds.badge(cr.stage_label("lead"), "info"), MANUAL_BADGE),
                              role="УК ещё нет в канонической таблице"),
                    unsafe_allow_html=True)
        if st.button("🏢 Завести УК в CRM", key=f"hydro_uk_create_{uk_inn}"):
            created = repo.ensure_company(name=str(uk_name or ""), inn=uk_inn)
            if created:
                st.success(f"УК создана (id {created}).")
                st.rerun()
            else:
                st.error("Не удалось создать УК: проверьте ИНН.")
        return
    render_uk_params(repo, company)
    render_uk_contacts(repo, int(company["id"]))
    render_uk_activities(repo, int(company["id"]))
