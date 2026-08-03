"""Companies page orchestrator."""
from typing import Optional

import streamlit as st

from src.services.companies_service import CompaniesService
from src.ui.companies_page_filters import render_filters
from src.ui.companies_page_tabs import render_company_tabs
from src.ui.company_detail import render_company_detail


def _show_dedup_notice(service: CompaniesService) -> None:
    if st.session_state.get("dedup_notice_shown"):
        return
    report = service.last_dedup_report
    removed_list = service._list_duplicates_removed
    parts = []
    if report and report.rows_removed:
        parts.append(f"в БД удалено {report.rows_removed} дублей профилей")
    if report and report.groups_merged:
        parts.append(f"объединено {report.groups_merged} групп по ИНН")
    if removed_list:
        parts.append(f"из списка убрано {removed_list} повторов")
    if parts:
        st.info("Проверка дублей: " + ", ".join(parts) + ". Сохранение идёт только по каноническому ИНН.")
    st.session_state.dedup_notice_shown = True


def render_companies_page(service: CompaniesService) -> None:
    """Render the main company registry page."""
    detail_inn: Optional[str] = st.session_state.get("detail_inn")
    if detail_inn:
        render_company_detail(service, detail_inn, on_back=_clear_detail)
        return
    st.title("Компании")
    st.caption("Разметка по реестрам. Изменения на карточках сохраняются в общую CRM-БД.")
    _show_dedup_notice(service)
    summary = service.summary
    if summary:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Всего компаний", summary.total_companies)
        m2.metric("С объектами", summary.with_objects)
        m3.metric("Объектов NashDom", summary.nashdom_objects)
        m4.metric("Избранных", len(service.favorite_companies()))
    search, region, grade, page_size = render_filters(service, summary)
    st.divider()

    def on_detail(inn: str) -> None:
        st.session_state.detail_inn = inn
        st.rerun()

    def on_saved() -> None:
        st.rerun()

    render_company_tabs(
        service, search=search, region=region, grade=grade, page_size=page_size,
        on_detail=on_detail, on_saved=on_saved,
    )


def _clear_detail() -> None:
    st.session_state.detail_inn = None
    st.rerun()
