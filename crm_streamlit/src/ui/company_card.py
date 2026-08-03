"""Краткая компактная карточка компании с пиктограммами."""
import html
from typing import Callable, List, Optional, Tuple

import streamlit as st

from modules.crm.analytics.analytics_models import DesignerAnalytics
from modules.crm.analytics.designer_profile_constants import (
    COMPANY_CATEGORIES,
    COMPANY_GRADES,
    GRADE_OTHER,
    GRADE_OTHER_LABEL,
    LEGAL_STATUSES,
)
from modules.crm.analytics.object_classifier import segment_label
from src.services.companies_service import CompaniesService
from src.ui.export_queue_ui import is_queued, migrate_queue_inn, toggle_export_for_inn
from src.ui.company_title import format_company_display_name

_SEGMENT_ICONS = {
    "residential": "🏠",
    "social": "🏛",
    "commercial": "🏬",
    "other": "📦",
}

_GRADE_OPTIONS: List[Tuple[Optional[str], str]] = (
    [(None, "—")]
    + [(g, g) for g in COMPANY_GRADES]
    + [(GRADE_OTHER, GRADE_OTHER_LABEL)]
)


def _category_options() -> List[Tuple[Optional[str], str]]:
    return [(None, "—")] + list(COMPANY_CATEGORIES)


def _clone_company(company: DesignerAnalytics, **kwargs) -> DesignerAnalytics:
    data = {
        "inn": company.inn,
        "full_name": company.full_name,
        "legal_form": company.legal_form,
        "region": company.region,
        "nashdom_count": company.nashdom_count,
        "nashdom_active": company.nashdom_active,
        "segments": company.segments,
        "nashdom_roles": list(company.nashdom_roles),
        "company_category": company.company_category,
        "company_grade": company.company_grade,
        "registry": company.registry,
        "website": company.website,
        "legal_status": company.legal_status,
        "is_favorite": company.is_favorite,
        "tender_count": company.tender_count,
        "has_nashdom": company.has_nashdom,
        "profile_key": company.profile_key,
    }
    data.update(kwargs)
    return DesignerAnalytics(**data)


def _toggle_favorite(service: CompaniesService, inn: str) -> None:
    company = service.get_company(inn)
    if not company or not service.profile_repo:
        return
    updated = _clone_company(company, is_favorite=not company.is_favorite)
    if service.save_profile_from_card(updated):
        st.toast("Избранное обновлено", icon="⭐")


def _show_save_notice(company: DesignerAnalytics) -> None:
    """Показать подтверждение после rerun (toast не переживает rerun)."""
    notice = st.session_state.get("company_save_notice")
    if notice and notice.get("inn") == company.inn:
        st.success("✅ Данные компании обновлены и сохранены в CRM")
        del st.session_state["company_save_notice"]


def _set_save_notice(company: DesignerAnalytics) -> None:
    st.session_state["company_save_notice"] = {
        "inn": company.inn,
        "name": company.full_name,
    }


def _toggle_pdf(inn: str) -> None:
    toggle_export_for_inn(inn)


def _card_title(company: DesignerAnalytics) -> str:
    """Только full_name/legal_form — без обращения к company.display_name."""
    return format_company_display_name(
        getattr(company, "full_name", None),
        getattr(company, "legal_form", None),
    )


def _render_stat_chip(column, icon: str, label: str, value) -> None:
    with column:
        st.markdown(
            f'<div class="crm-chip"><span class="crm-chip-ico">{icon}</span>'
            f'<span class="crm-chip-val">{html.escape(str(value))}</span>'
            f'<span class="crm-chip-lbl">{label}</span></div>',
            unsafe_allow_html=True,
        )


def _stable_card_id(company: DesignerAnalytics) -> str:
    """Стабильный id виджетов (ключ Radar в CRM, не меняется при override ИНН)."""
    return company.profile_key or company.inn


def render_company_card(
    service: CompaniesService,
    company: DesignerAnalytics,
    card_key: str,
    on_detail: Callable[[str], None],
    on_saved: Callable[[], None],
) -> None:
    """Компактная карточка: крупная шапка + одна строка редактирования."""
    readonly = service.profile_repo is None
    in_pdf = is_queued(company.inn)
    stable_id = _stable_card_id(company)

    with st.container(border=True):
        r_flags, r_title, r_btn = st.columns([0.1, 0.7, 0.2])
        with r_flags:
            flag_fav, flag_pdf = st.columns(2)
            with flag_fav:
                st.button(
                    "★" if company.is_favorite else "☆",
                    key=f"fav_btn_{card_key}_{stable_id}",
                    help="Избранное",
                    disabled=readonly,
                    on_click=_toggle_favorite,
                    args=(service, company.inn),
                    type="tertiary",
                )
            with flag_pdf:
                st.button(
                    "📥" if in_pdf else "📄",
                    key=f"pdf_btn_{card_key}_{stable_id}",
                    help="В очереди PDF" if in_pdf else "Добавить в выгрузку PDF",
                    on_click=_toggle_pdf,
                    args=(company.inn,),
                    type="tertiary",
                )
        with r_title:
            st.markdown(
                f'<p class="crm-card-name">{html.escape(_card_title(company))}</p>',
                unsafe_allow_html=True,
            )
        with r_btn:
            if st.button(
                "Подробнее",
                key=f"detail_{card_key}_{stable_id}",
                type="primary",
                use_container_width=True,
            ):
                on_detail(company.inn)

        seg_items = [
            (key, getattr(company.segments, key))
            for key in ("residential", "social", "commercial", "other")
            if getattr(company.segments, key) > 0
        ]
        extra_cols = len(seg_items) + (1 if company.tender_count else 0)
        chips = st.columns(4 + extra_cols)
        _render_stat_chip(chips[0], "📍", "Регион", company.region)
        _render_stat_chip(chips[1], "🆔", "ИНН", company.inn)
        _render_stat_chip(chips[2], "🏗", "NashDom", company.nashdom_count)
        _render_stat_chip(chips[3], "🚧", "Строится", company.nashdom_active)
        idx = 4
        for key, cnt in seg_items:
            short = segment_label(key).split("(")[0].strip()[:6]
            _render_stat_chip(chips[idx], _SEGMENT_ICONS[key], short, cnt)
            idx += 1
        if company.tender_count:
            _render_stat_chip(chips[idx], "📋", "Закуп.", company.tender_count)

        if readonly:
            if company.website:
                st.caption(f"🌐 {company.website}")
            return

        cat_labels = [label for _, label in _category_options()]
        cat_codes = [code for code, _ in _category_options()]
        cat_idx = (
            cat_codes.index(company.company_category)
            if company.company_category in cat_codes else 0
        )
        grade_labels = [label for _, label in _GRADE_OPTIONS]
        grade_codes = [code for code, _ in _GRADE_OPTIONS]
        grade_idx = (
            grade_codes.index(company.company_grade)
            if company.company_grade in grade_codes else 0
        )
        status_codes = [code for code, _ in LEGAL_STATUSES]
        status_labels = [label for _, label in LEGAL_STATUSES]
        status_idx = (
            status_codes.index(company.legal_status)
            if company.legal_status in status_codes else 0
        )

        st.markdown('<div class="crm-card-edit">', unsafe_allow_html=True)
        with st.form(key=f"card_form_{card_key}_{stable_id}", clear_on_submit=False):
            n1, n2 = st.columns([2.4, 1])
            with n1:
                full_name_input = st.text_input(
                    "Название",
                    value=company.full_name or "",
                    placeholder="Полное название компании",
                    label_visibility="collapsed",
                )
            with n2:
                inn_input = st.text_input(
                    "ИНН",
                    value=company.inn or "",
                    placeholder="ИНН (10 или 12 цифр)",
                    label_visibility="collapsed",
                )
            c1, c2, c3, c4, c5 = st.columns([1.15, 1.25, 0.95, 0.5, 0.22])
            with c1:
                category_label = st.selectbox(
                    "Категория",
                    options=cat_labels,
                    index=cat_idx,
                    label_visibility="collapsed",
                )
            with c2:
                website = st.text_input(
                    "Сайт",
                    value=company.website or "",
                    placeholder="🌐 сайт",
                    label_visibility="collapsed",
                )
            with c3:
                legal_status_label = st.selectbox(
                    "Статус",
                    options=status_labels,
                    index=status_idx,
                    label_visibility="collapsed",
                )
            with c4:
                grade_label = st.selectbox(
                    "Класс",
                    options=grade_labels,
                    index=grade_idx,
                    label_visibility="collapsed",
                )
            with c5:
                submitted = st.form_submit_button(
                    "💾",
                    help="Сохранить",
                    use_container_width=True,
                )
        st.markdown("</div>", unsafe_allow_html=True)

        _show_save_notice(company)

        if submitted:
            previous_inn = company.inn
            profile_key = company.profile_key or company.inn
            updated = _clone_company(
                company,
                inn=inn_input.strip(),
                full_name=full_name_input.strip(),
                company_category=cat_codes[cat_labels.index(category_label)],
                company_grade=grade_codes[grade_labels.index(grade_label)],
                website=website.strip() or None,
                legal_status=status_codes[status_labels.index(legal_status_label)],
                profile_key=profile_key,
            )
            if service.save_profile_from_card(
                updated,
                profile_key=profile_key,
                previous_display_inn=previous_inn,
            ):
                migrate_queue_inn(previous_inn, updated.inn)
                _set_save_notice(updated)
                on_saved()
            else:
                st.error(service.last_error or "Не удалось сохранить — проверьте подключение к CRM")
