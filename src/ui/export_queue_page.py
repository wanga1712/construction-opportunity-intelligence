"""Страница очереди PDF-выгрузки."""
from datetime import datetime
from typing import List, Optional

import streamlit as st

from modules.crm.analytics.analytics_models import DesignerAnalytics
from modules.crm.analytics.designer_profile_constants import (
    COMPANY_CATEGORY_LABELS,
    REGISTRY_LABELS,
)
from modules.crm.analytics.object_classifier import segment_label
from src.services.companies_service import CompaniesService
from src.ui.export_queue_ui import clear_queue, list_queued_inns, remove_from_queue
from src.services.export_sort import grade_section_label, load_queued_companies_split
from src.ui.company_title import get_company_display_name
from src.services.pdf_export import (
    REPORTLAB_AVAILABLE,
    CARDS_PER_SHEET,
    CARDS_PER_SPREAD,
    CompaniesPdfExporter,
    card_from_company,
)


def _segment_line(company: DesignerAnalytics) -> str:
    parts = []
    for key in ("residential", "social", "commercial", "other"):
        cnt = getattr(company.segments, key)
        if cnt > 0:
            parts.append(f"{segment_label(key)}: {cnt}")
    return " · ".join(parts) if parts else "—"


def _render_ready_pdf_block(key_prefix: str, label: str) -> bool:
    """Блок скачивания готового PDF."""
    bytes_key = f"last_pdf_bytes_{key_prefix}"
    name_key = f"last_pdf_name_{key_prefix}"
    count_key = f"last_export_count_{key_prefix}"

    pdf_bytes = st.session_state.get(bytes_key)
    if not pdf_bytes:
        return False

    count = st.session_state.get(count_key, 0)
    st.success(f"{label}: {count} компаний. Скачайте файл ниже.")
    st.download_button(
        label=f"⬇️ Скачать {label} ({count})",
        data=pdf_bytes,
        file_name=st.session_state.get(name_key, "companies.pdf"),
        mime="application/pdf",
        type="primary",
        use_container_width=True,
        key=f"download_{key_prefix}",
    )
    if st.button("✕ Скрыть", key=f"dismiss_{key_prefix}"):
        st.session_state.pop(bytes_key, None)
        st.session_state.pop(name_key, None)
        st.session_state.pop(count_key, None)
        st.rerun()
    st.divider()
    return True


def _render_queue_item(company: DesignerAnalytics, key_suffix: str) -> None:
    with st.container(border=True):
        c1, c2, c3 = st.columns([5, 3, 1])
        with c1:
            st.markdown(f"**{get_company_display_name(company)}**")
            st.caption(
                f"ИНН {company.inn} · {company.region} · "
                f"NashDom {company.nashdom_count} · Строится {company.nashdom_active}"
            )
        with c2:
            st.caption(_segment_line(company))
            st.caption(
                f"{COMPANY_CATEGORY_LABELS.get(company.company_category or '', '—')} · "
                f"класс {company.company_grade or '—'} · "
                f"{REGISTRY_LABELS.get(company.registry or '', '—')}"
            )
        with c3:
            if st.button("✕", key=f"rm_{key_suffix}_{company.inn}", help="Убрать из очереди"):
                remove_from_queue(company.inn)
                st.rerun()


def _render_sorted_list(
    companies: List[DesignerAnalytics],
    key_suffix: str,
) -> None:
    prev_section: Optional[str] = None
    for company in companies:
        section = grade_section_label(company)
        if section != prev_section:
            st.markdown(f"**{section}**")
            prev_section = section
        _render_queue_item(company, key_suffix)


def _build_pdf(companies: List[DesignerAnalytics], fname_prefix: str) -> Optional[tuple]:
    if not companies:
        return None
    cards = [card_from_company(c) for c in companies]
    pdf_bytes = CompaniesPdfExporter().build_pdf_bytes(cards)
    if not pdf_bytes:
        return None
    fname = f"{fname_prefix}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    return pdf_bytes, fname, len(companies)


def render_export_queue_page(service: CompaniesService) -> None:
    st.title("📄 Выгрузка PDF")
    st.caption(
        "Порядок **основной** очереди: **A → B → C → без типа (не установлено) → E → D (в конце)**. "
        "Категория **«Другое»** — отдельный блок и отдельный PDF. "
        f"**{CARDS_PER_SHEET}** карточек на лист A4, **{CARDS_PER_SPREAD}** на два листа."
    )

    if not REPORTLAB_AVAILABLE:
        st.error("Установите reportlab: `pip install reportlab`")
        return

    has_main_pdf = _render_ready_pdf_block("main", "Основной PDF")
    has_other_pdf = _render_ready_pdf_block("other", "PDF «Другое»")

    inns = list_queued_inns()
    main_companies, other_companies = load_queued_companies_split(service, inns)
    n_total = len(main_companies) + len(other_companies)

    m1, m2, m3 = st.columns(3)
    m1.metric("В очереди", n_total)
    m2.metric("Основная", len(main_companies))
    m3.metric("Другое", len(other_companies))

    if not main_companies and not other_companies:
        if not has_main_pdf and not has_other_pdf:
            st.info("Очередь пуста. На странице «Компании» отметьте карточки для выгрузки (📄).")
        return

    st.divider()

    if st.button("🗑 Очистить всю очередь", type="secondary"):
        clear_queue()
        st.rerun()

    if main_companies:
        st.subheader("Основная очередь")
        _render_sorted_list(main_companies, "main")
        st.divider()
        if st.button("📥 Сформировать основной PDF", type="primary", use_container_width=True):
            result = _build_pdf(main_companies, "companies")
            if not result:
                st.error("Не удалось сформировать PDF")
            else:
                pdf_bytes, fname, count = result
                for c in main_companies:
                    remove_from_queue(c.inn)
                st.session_state.last_pdf_bytes_main = pdf_bytes
                st.session_state.last_pdf_name_main = fname
                st.session_state.last_export_count_main = count
                st.rerun()

    if other_companies:
        st.subheader("Другое (отдельная выгрузка)")
        st.caption("Компании с категорией «Другое» — не попадают в основной PDF.")
        for company in other_companies:
            _render_queue_item(company, "other")
        st.divider()
        if st.button("📥 Сформировать PDF «Другое»", type="secondary", use_container_width=True):
            result = _build_pdf(other_companies, "companies_other")
            if not result:
                st.error("Не удалось сформировать PDF")
            else:
                pdf_bytes, fname, count = result
                for c in other_companies:
                    remove_from_queue(c.inn)
                st.session_state.last_pdf_bytes_other = pdf_bytes
                st.session_state.last_pdf_name_other = fname
                st.session_state.last_export_count_other = count
                st.rerun()

    # Совместимость со старыми ключами session_state
    if st.session_state.get("last_pdf_bytes") and not st.session_state.get("last_pdf_bytes_main"):
        st.session_state.last_pdf_bytes_main = st.session_state.pop("last_pdf_bytes")
        st.session_state.last_pdf_name_main = st.session_state.pop("last_pdf_name", "companies.pdf")
        st.session_state.last_export_count_main = st.session_state.pop("last_export_count", 0)
