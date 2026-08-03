"""
Панель редактирования выбранной компании.
"""
from typing import Callable, List, Optional, Tuple

import streamlit as st

from modules.crm.analytics.analytics_models import DesignerAnalytics
from modules.crm.analytics.designer_profile_constants import (
    COMPANY_CATEGORIES,
    COMPANY_CATEGORY_LABELS,
    COMPANY_GRADES,
    GRADE_OTHER,
    GRADE_OTHER_LABEL,
    LEGAL_STATUSES,
    REGISTRIES,
    REGISTRY_LABELS,
)
from src.services.companies_service import CompaniesService
from src.ui.company_title import get_company_display_name


def _category_options() -> List[Tuple[Optional[str], str]]:
    return [(None, "— не задано —")] + list(COMPANY_CATEGORIES)


def _grade_options() -> List[Tuple[Optional[str], str]]:
    return [(None, "— не задано —")] + [(g, g) for g in COMPANY_GRADES] + [(GRADE_OTHER, GRADE_OTHER_LABEL)]


def _registry_options() -> List[Tuple[Optional[str], str]]:
    return [(None, "— авто —")] + list(REGISTRIES)


def _render_readonly(company: DesignerAnalytics) -> None:
    """Показать поля профиля без возможности сохранения."""
    st.checkbox("⭐ Избранное", value=company.is_favorite, disabled=True)
    cat_label = COMPANY_CATEGORY_LABELS.get(company.company_category or "", "— не задано —")
    st.text_input("Категория компании", value=cat_label, disabled=True)
    grade_label = company.company_grade or "— не задано —"
    st.text_input("Класс", value=grade_label, disabled=True)
    reg_label = REGISTRY_LABELS.get(company.registry or "", "— авто —")
    st.text_input("Реестр (вкладка)", value=reg_label, disabled=True)
    st.text_input("Сайт", value=company.website or "", disabled=True)
    status_labels = {code: label for code, label in LEGAL_STATUSES}
    st.text_input(
        "Юридический статус",
        value=status_labels.get(company.legal_status or "", "—"),
        disabled=True,
    )


def render_edit_panel(
    service: CompaniesService,
    company: Optional[DesignerAnalytics],
    on_saved: Callable[[], None],
) -> None:
    """Форма редактирования профиля компании."""
    st.subheader("Настройка компании")

    if not company:
        st.info("Выберите строку в таблице слева.")
        return

    readonly = service.profile_repo is None
    if readonly:
        st.warning("CRM БД недоступна — сохранение профилей отключено (режим просмотра).")

    st.markdown(f"**{get_company_display_name(company)}**")
    st.caption(f"ИНН {company.inn} · {company.region} · объектов: {company.total_objects}")

    seg = company.segments
    cols = st.columns(4)
    cols[0].metric("Жилое", seg.residential)
    cols[1].metric("Соц.", seg.social)
    cols[2].metric("Комм.", seg.commercial)
    cols[3].metric("Другое", seg.other)

    if readonly:
        _render_readonly(company)
    else:
        cat_labels = [label for _, label in _category_options()]
        cat_codes = [code for code, _ in _category_options()]
        cat_idx = cat_codes.index(company.company_category) if company.company_category in cat_codes else 0

        grade_labels = [label for _, label in _grade_options()]
        grade_codes = [code for code, _ in _grade_options()]
        grade_idx = grade_codes.index(company.company_grade) if company.company_grade in grade_codes else 0

        reg_labels = [label for _, label in _registry_options()]
        reg_codes = [code for code, _ in _registry_options()]
        reg_idx = reg_codes.index(company.registry) if company.registry in reg_codes else 0

        status_codes = [code for code, _ in LEGAL_STATUSES]
        status_labels = [label for _, label in LEGAL_STATUSES]
        status_idx = (
            status_codes.index(company.legal_status)
            if company.legal_status in status_codes
            else 0
        )

        with st.form(key=f"edit_{company.inn}", clear_on_submit=False):
            is_favorite = st.checkbox("⭐ Избранное", value=company.is_favorite)
            company_category = st.selectbox("Категория компании", options=cat_labels, index=cat_idx)
            company_grade = st.selectbox("Класс", options=grade_labels, index=grade_idx)
            registry = st.selectbox("Реестр (вкладка)", options=reg_labels, index=reg_idx)
            website = st.text_input("Сайт", value=company.website or "")
            legal_status = st.selectbox("Юридический статус", options=status_labels, index=status_idx)
            submitted = st.form_submit_button("Сохранить", type="primary", use_container_width=True)

        if submitted:
            updated = DesignerAnalytics(
                inn=company.inn,
                full_name=company.full_name,
                legal_form=company.legal_form,
                region=company.region,
                nashdom_count=company.nashdom_count,
                nashdom_active=company.nashdom_active,
                segments=company.segments,
                nashdom_roles=list(company.nashdom_roles),
                company_category=cat_codes[cat_labels.index(company_category)],
                company_grade=grade_codes[grade_labels.index(company_grade)],
                registry=reg_codes[reg_labels.index(registry)],
                website=website.strip() or None,
                legal_status=status_codes[status_labels.index(legal_status)],
                is_favorite=is_favorite,
                tender_count=company.tender_count,
                has_nashdom=company.has_nashdom,
            )
            if service.apply_company_change(updated):
                st.success("Сохранено — профиль общий с десктопным CRM.")
                on_saved()
            else:
                st.error("Не удалось сохранить профиль.")

    if company.nashdom_roles:
        roles_txt = ", ".join(company.nashdom_roles)
        st.caption(f"Роли NashDom: {roles_txt}")

    reg_txt = REGISTRY_LABELS.get(company.registry or "", "—")
    cat_txt = COMPANY_CATEGORY_LABELS.get(company.company_category or "", "—")
    st.caption(f"Текущий реестр: {reg_txt} · категория: {cat_txt}")
