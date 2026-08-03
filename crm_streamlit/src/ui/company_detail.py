"""Полная карточка компании: метрики и список объектов (без HTML-блоков)."""
import html
from typing import Callable, List

import streamlit as st

from modules.crm.analytics.analytics_models import DesignerAnalytics, DesignerObject
from modules.crm.analytics.designer_profile_constants import (
    COMPANY_CATEGORY_LABELS,
    NASHDOM_ROLE_LABELS,
    REGISTRY_LABELS,
)
from modules.crm.analytics.object_classifier import segment_label
from src.services.companies_service import CompaniesService
from src.ui.company_title import get_company_display_name

STATUS_BUILDING = "Строится"


def _tender_source_label(obj: DesignerObject) -> str:
    """Подпись источника закупки по метке реестра."""
    status = (obj.status or "").lower()
    if "615" in status:
        return "615 ПП"
    if "223" in status:
        return "223-ФЗ"
    if "44" in status:
        return "44-ФЗ"
    return "Закупка"


def _render_object_row(obj: DesignerObject) -> None:
    """Одна строка объекта — нативные виджеты."""
    with st.container(border=True):
        title_l, title_r = st.columns([4, 1])
        with title_l:
            st.markdown(f"**{html.escape(obj.name)}**")
        with title_r:
            st.caption(segment_label(obj.segment))

        if obj.address:
            st.caption(obj.address)

        role = ""
        if obj.party_role:
            role = NASHDOM_ROLE_LABELS.get(obj.party_role, obj.party_role)
        source = "NashDom" if obj.source == "nashdom" else _tender_source_label(obj)
        status = obj.status or "—"
        extra = f"{source}"
        if role:
            extra += f" · {role}"
        extra += f" · {status}"
        st.caption(extra)


def _filter_objects(
    objects: List[DesignerObject],
    mode: str,
) -> List[DesignerObject]:
    if mode == "building":
        return [o for o in objects if o.source == "nashdom" and o.status == STATUS_BUILDING]
    if mode == "completed":
        return [
            o for o in objects
            if o.source == "nashdom" and o.status and o.status != STATUS_BUILDING
        ]
    if mode == "tender":
        return [o for o in objects if o.source == "tender"]
    return objects


def render_company_detail(
    service: CompaniesService,
    inn: str,
    on_back: Callable[[], None],
) -> None:
    """Страница детализации компании."""
    company = service.get_company(inn)
    if not company:
        st.warning("Компания не найдена.")
        if st.button("← Назад к списку"):
            on_back()
        return

    if st.button("← Назад к списку"):
        on_back()
        return

    roles = ", ".join(NASHDOM_ROLE_LABELS.get(r, r) for r in company.nashdom_roles)
    cat = COMPANY_CATEGORY_LABELS.get(company.company_category or "", "—")
    reg = REGISTRY_LABELS.get(company.registry or "", "—")

    st.subheader(get_company_display_name(company))
    meta = f"ИНН {company.inn} · {company.region}"
    if roles:
        meta += f" · {roles}"
    st.caption(meta)
    line2 = f"{cat} · класс {company.company_grade or '—'} · {reg}"
    if company.website:
        line2 += f" · {company.website}"
    st.caption(line2)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("NashDom всего", company.nashdom_count)
    m2.metric("Строится", company.nashdom_active)
    m3.metric("Сдано", max(0, company.nashdom_count - company.nashdom_active))
    m4.metric("Закупки", company.tender_count)
    m5.metric("Всего", company.total_objects)

    seg = company.segments
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Жилое", seg.residential)
    s2.metric("Соц.", seg.social)
    s3.metric("Комм.", seg.commercial)
    s4.metric("Другое", seg.other)

    with st.spinner("Загрузка объектов…"):
        objects = service.get_company_objects(inn)

    building = [o for o in objects if o.source == "nashdom" and o.status == STATUS_BUILDING]
    completed = [
        o for o in objects
        if o.source == "nashdom" and o.status and o.status != STATUS_BUILDING
    ]
    tenders = [o for o in objects if o.source == "tender"]

    st.subheader("Объекты компании")
    st.caption(
        "Статусы NashDom: **Строится** — объекты в работе; **Сдан** — завершённые."
    )

    tab_all, tab_build, tab_done, tab_tender = st.tabs([
        f"Все ({len(objects)})",
        f"Строится ({len(building)})",
        f"Сдано ({len(completed)})",
        f"Закупки ({len(tenders)})",
    ])

    for tab, mode in (
        (tab_all, "all"),
        (tab_build, "building"),
        (tab_done, "completed"),
        (tab_tender, "tender"),
    ):
        with tab:
            shown = _filter_objects(objects, mode)
            if not shown:
                st.info("Нет объектов в этой категории.")
                continue
            for obj in shown:
                _render_object_row(obj)
