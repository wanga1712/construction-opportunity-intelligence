"""Страница аналитического контура v2 (§14.1–14.3)."""
from __future__ import annotations

import streamlit as st

from src.ui.components.analytics_v2.analytics_expander import render_charts
from src.ui.components.analytics_v2.header import render_header
from src.ui.components.analytics_v2.kpi_row import render_kpi_row
from src.ui.components.analytics_v2.limits import render_limits
from src.ui.components.analytics_v2.mock_data import CARDS
from src.ui.components.analytics_v2.quick_filters import render_quick_filters
from src.ui.components.analytics_v2.tabs import render_tabs

_STICKY_CSS = """
<style>
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child {
    position: -webkit-sticky;
    position: sticky;
    top: 3rem;
    max-height: calc(100vh - 4rem);
    overflow-y: auto;
    align-self: flex-start;
}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child::-webkit-scrollbar {
    width: 4px;
}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child::-webkit-scrollbar-thumb {
    background: #ccc;
    border-radius: 2px;
}
</style>
"""


def render_analytics_contour_v2_page(service) -> None:
    """Шапка → KPI → Лимит → Три графика → [Фильтры | Рабочая область]."""
    st.session_state["analytics_v2_cards"] = CARDS

    st.markdown(_STICKY_CSS, unsafe_allow_html=True)

    render_header()
    render_kpi_row()
    render_limits()
    st.divider()
    render_charts()
    st.divider()

    left, right = st.columns([1, 3], gap="medium")

    with left:
        _render_filters()

    with right:
        render_quick_filters()
        render_tabs()


def _render_filters() -> None:
    """Панель фильтров — левая колонка, динамические данные из БД."""
    from src.services.crm_profile_service import load_profiles, load_subcategories

    st.markdown("**ФИЛЬТРЫ**")

    # --- Профиль ---
    profiles = load_profiles()
    profile_options = [{"id": None, "name": "Все профили"}] + profiles
    selected_profile = st.selectbox(
        "Профиль",
        options=[p["id"] for p in profile_options],
        format_func=lambda pid: next(
            (p["name"] for p in profile_options if p["id"] == pid), "—"
        ),
        key="analytics_v2_profile_filter",
    )

    # --- Подкатегория / Категория ---
    subcats = load_subcategories(selected_profile) if selected_profile else load_subcategories()
    if subcats:
        cat_options = ["Все"] + subcats
        st.selectbox("Категория", cat_options, index=0, key="analytics_v2_category_filter")
    else:
        # Запасной вариант — уникальные crm_category из закупок
        from src.ui.analytics_contour_v2_page import _load_categories_from_db
        db_cats = _load_categories_from_db()
        st.selectbox("Категория", ["Все"] + db_cats, index=0, key="analytics_v2_category_filter")

    # --- Уровень ---
    st.segmented_control(
        "Уровень",
        ["Все", "Gold", "Silver", "Bronze"],
        default="Все",
        selection_mode="single",
        key="analytics_v2_level_filter",
    )

    # --- Регион ---
    st.selectbox(
        "Регион",
        ["Все регионы", "Московская область", "Москва", "Санкт-Петербург", "Нижегородская область"],
        index=0,
        key="analytics_v2_region_filter",
    )

    st.selectbox("Тип объекта", ["Все", "Социальный", "Инфраструктурный", "Жилой"], index=0)
    st.selectbox("Заказчик", ["Все"], index=0)

    st.radio(
        "Показывать",
        ["Все", "Новые", "Обновлённые", "Сохранённые"],
        index=0,
        key="analytics_v2_show_mode",
    )

    st.button("Расширенные фильтры", use_container_width=True)
    if st.button("Сбросить фильтры", use_container_width=True):
        for key in ["analytics_v2_profile_filter", "analytics_v2_category_filter",
                    "analytics_v2_level_filter", "analytics_v2_region_filter",
                    "analytics_v2_show_mode"]:
            st.session_state.pop(key, None)
        st.rerun()


@st.cache_data(ttl=120, show_spinner=False)
def _load_categories_from_db() -> list[str]:
    """Уникальные crm_category из crm_procurements (запасной вариант)."""
    try:
        import os, psycopg2
        from psycopg2.extras import RealDictCursor
        PG = dict(
            host=os.environ.get("CRM_DB_HOST", "10.8.0.7"),
            port=int(os.environ.get("CRM_DB_PORT", 5432)),
            user=os.environ.get("CRM_DB_USER", "postgres"),
            password=os.environ.get("CRM_DB_PASSWORD", "0IFz3_"),
            dbname="crm",
        )
        conn = psycopg2.connect(**PG)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT DISTINCT crm_category FROM crm_procurements
                WHERE crm_category IS NOT NULL AND crm_category != ''
                ORDER BY crm_category
            """)
            cats = [r["crm_category"] for r in cur.fetchall()]
        conn.close()
        return cats
    except Exception:
        return []
