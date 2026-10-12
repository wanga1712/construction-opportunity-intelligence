"""Waterproofing CRM page: the УК board is the main screen, objects come second.

The section runs two linked funnels — accounts (УК) and deals (objects) — so the
screen switcher keeps the board first and the reference screens after it.
"""
from __future__ import annotations

import streamlit as st

from src.services.objects_service import ObjectsService
from src.ui.hydro_object_card import render_hydro_objects_screen
from src.ui.waterproofing_kanban_tab import render_kanban_tab
from src.ui.waterproofing_map_tab import render_map_tab
from src.ui.waterproofing_meta_tabs import render_ai_tab, render_fields_tab, render_pipeline_tab
from src.ui.waterproofing_objects_tab import render_objects_tab
from src.ui.waterproofing_uk_tab import render_uk_card

SCREEN_KANBAN = "🔷 Доска: УК и объекты"
SCREEN_MAP = "🗺 Карта объектов"
SCREEN_PARKING = "🅿️ Паркинги и объекты (карточки)"
SCREEN_OBJECTS = "🔥 Объекты из БД"
SCREEN_PIPELINE = "📍 Воронки"
SCREEN_FIELDS = "🧾 Поля / скоринг"
SCREEN_AI = "🤖 AI / база знаний"

SCREENS = [SCREEN_KANBAN, SCREEN_PARKING, SCREEN_MAP, SCREEN_OBJECTS,
           SCREEN_PIPELINE, SCREEN_FIELDS, SCREEN_AI]


def render_waterproofing_page(service: ObjectsService) -> None:
    """Render the УК-centric waterproofing CRM."""
    open_key = st.session_state.get("hydro_open_uk")
    if open_key:
        st.title("💧 Гидроизоляция — карточка УК")
        render_uk_card(service, str(open_key))
        return

    st.title("💧 Гидроизоляция")
    st.caption("Управляющие компании и объекты")
    st.caption("Работа с УК → обследование → техрешение → ТЗ → закупка → контракт")
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
