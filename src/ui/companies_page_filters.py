"""Filter controls for the companies page."""
import streamlit as st

from modules.crm.analytics.designer_profile_constants import GRADE_OTHER, GRADE_OTHER_LABEL
from src.services.companies_service import CompaniesService


def render_filters(service: CompaniesService, summary) -> tuple:
    """Render page filters and return the selected values."""
    st.markdown("#### Настройки вывода")
    c1, c2, c3, c4, c5, c6 = st.columns([2, 1.2, 1, 1, 1, 1])
    with c1:
        search = st.text_input("Поиск", placeholder="Название или ИНН", label_visibility="collapsed")

    regions = ["Все регионы"]
    if summary:
        regions += sorted(summary.by_region.keys())
    with c2:
        region_sel = st.selectbox("Регион", regions, index=0, label_visibility="collapsed")
    region = None if region_sel == "Все регионы" else region_sel

    grade_options = {
        "Все классы": None,
        "A": "A", "B": "B", "C": "C", "D": "D", "E": "E",
        GRADE_OTHER_LABEL: GRADE_OTHER,
    }
    with c3:
        grade_sel = st.selectbox(
            "Класс", list(grade_options.keys()), index=0, label_visibility="collapsed",
        )
    grade = grade_options[grade_sel]

    with c4:
        st.session_state.favorites_only = st.toggle(
            "⭐ Только избранные", value=st.session_state.get("favorites_only", False),
        )
    with c5:
        page_size = st.selectbox(
            "На странице", options=[26, 52, 100], index=1, label_visibility="collapsed",
        )
    with c6:
        if st.button("↻ Обновить", use_container_width=True):
            with st.spinner("Обновление…"):
                ok = service.load_sync(refresh_matview=True)
            if ok:
                st.success("Данные обновлены")
                st.rerun()
            else:
                st.error(service.last_error or "Ошибка")
    return search, region, grade, page_size
