"""Waterproofing CRM page: the УК kanban is the main screen, objects come second."""
from __future__ import annotations

import streamlit as st

from src.services.objects_service import ObjectsService
from src.ui.waterproofing_kanban_tab import render_kanban_tab
from src.ui.waterproofing_map_tab import render_map_tab
from src.ui.waterproofing_meta_tabs import render_ai_tab, render_fields_tab, render_pipeline_tab
from src.ui.waterproofing_objects_tab import render_objects_tab
from src.ui.hydro_object_card import render_hydro_objects_screen

SCREEN_KANBAN = "🔷 CRM-канбан УК"
SCREEN_MAP = "🗺 Карта объектов"
SCREEN_PARKING = "🅿️ Паркинги и объекты (карточки)"
SCREEN_OBJECTS = "🔥 Объекты из БД"
SCREEN_PIPELINE = "📍 Воронки"
SCREEN_FIELDS = "🧾 Поля / скоринг"
SCREEN_AI = "🤖 AI / база знаний"

SCREENS = [SCREEN_KANBAN, SCREEN_PARKING, SCREEN_MAP, SCREEN_OBJECTS, SCREEN_PIPELINE, SCREEN_FIELDS, SCREEN_AI]


def render_waterproofing_page(service: ObjectsService) -> None:
    """Render the УК-centric waterproofing CRM."""
    if st.session_state.get("hydro_open_object"):
        st.title("💧 Гидроизоляция — карточка объекта")
        render_hydro_objects_screen(service)
        return
    st.title("💧 Гидроизоляция — CRM управляющих компаний")
    st.caption(
        "Главная сущность — управляющая компания и её контур. Экран отвечает на вопрос: "
        "с какими УК мы работаем, где они в воронке и что сделать следующим шагом. "
        "Карта объектов — вторичный экран."
    )
    screen = st.radio(
        "Экран", SCREENS, index=0, horizontal=True, key="hydro_screen", label_visibility="collapsed"
    )
    if screen == SCREEN_KANBAN:
        render_kanban_tab(service)
    elif screen == SCREEN_PARKING:
        render_hydro_objects_screen(service)
    elif screen == SCREEN_MAP:
        render_map_tab(service)
    elif screen == SCREEN_OBJECTS:
        render_objects_tab(service)
    elif screen == SCREEN_PIPELINE:
        render_pipeline_tab()
    elif screen == SCREEN_FIELDS:
        render_fields_tab()
    else:
        render_ai_tab()
