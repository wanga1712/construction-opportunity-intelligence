"""Waterproofing CRM page composition."""
from __future__ import annotations

import streamlit as st

from src.services.objects_service import ObjectsService
from src.ui.waterproofing_map_tab import render_map_tab
from src.ui.waterproofing_meta_tabs import render_ai_tab, render_fields_tab, render_pipeline_tab
from src.ui.waterproofing_objects_tab import render_objects_tab
from src.ui.waterproofing_uk_tab import render_uk_tab
from src.ui.hydro_leads_tab import render_hydro_leads_tab


def render_waterproofing_page(service: ObjectsService) -> None:
    st.title("💧 Гидроизоляция")
    st.caption(
        "Объектный CRM-процесс для подземных паркингов, подвалов, технологических вводов, "
        "деформационных швов и протечек. Данные берутся из текущей боевой БД CRM."
    )

    tab_leads, tab_uk, tab_objects, tab_map, tab_pipeline, tab_fields, tab_ai = st.tabs([
        "🔥 Лиды", "🏢 УК / контуры",
        "🔥 Объекты из БД",
        "🗺 Карта",
        "📍 Воронка",
        "🧾 Поля / скоринг",
        "🤖 AI / база знаний",
    ])
    with tab_leads:
        render_hydro_leads_tab(getattr(service, "crm_db", None))
    with tab_uk:
        render_uk_tab(service)
    with tab_objects:
        render_objects_tab(service)
    with tab_map:
        render_map_tab(service)
    with tab_pipeline:
        render_pipeline_tab()
    with tab_fields:
        render_fields_tab()
    with tab_ai:
        render_ai_tab()
