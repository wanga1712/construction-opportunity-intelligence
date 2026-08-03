"""CRM sidebar navigation."""
import streamlit as st

from src.ui.db_health_ui import apply_health_to_session, check_and_reconnect
from src.ui.export_queue_ui import queue_size

PAGES = {
    "companies": ("🏢", "Компании"),
    "objects": ("🏗️", "Закупочный контур"),
    "opportunity_radar": ("📡", "Радар объектов"),
    "computers": ("💻", "Компьютеры"),
    "waterproofing": ("💧", "Гидроизоляция"),
    "map": ("🗺", "Карта"),
    "infrastructure": ("🖥", "Инфраструктура"),
    "monitoring": ("📊", "Мониторинг"),
    "customers": ("👥", "Заказчики"),
    "export_pdf": ("📄", "Выгрузка PDF"),
}

FUTURE_PAGES = [
    ("deals", "📋", "Сделки"),
    ("analytics", "📊", "Аналитика"),
]


def render_sidebar_nav() -> str:
    """Render sidebar menu and return active page key."""
    st.sidebar.markdown("### CRM Система")
    st.sidebar.caption("Веб-инструмент разметки")

    theme_options = {"light": "Светлая", "dark": "Тёмная"}
    current_theme = st.session_state.get("ui_theme", "light")
    selected_theme = st.sidebar.radio(
        "Тема",
        list(theme_options.keys()),
        format_func=lambda key: theme_options[key],
        index=list(theme_options.keys()).index(current_theme)
        if current_theme in theme_options
        else 0,
        horizontal=True,
        key="ui_theme_radio",
    )
    if selected_theme != current_theme:
        st.session_state.ui_theme = selected_theme
        st.rerun()

    current = st.session_state.get("nav_page", "objects")

    for key, (icon, label) in PAGES.items():
        btn_label = label
        if key == "export_pdf":
            n = queue_size()
            if n:
                btn_label = f"{label} ({n})"
        if st.sidebar.button(
            f"{icon}  {btn_label}",
            key=f"nav_{key}",
            use_container_width=True,
            type="primary" if current == key else "secondary",
        ):
            st.session_state.nav_page = key
            st.session_state.detail_inn = None
            st.session_state.pop("object_detail_key", None)
            st.rerun()

    st.sidebar.markdown('<p class="crm-nav-caption">Скоро</p>', unsafe_allow_html=True)
    for key, icon, label in FUTURE_PAGES:
        st.sidebar.button(
            f"{icon}  {label}",
            key=f"nav_future_{key}",
            use_container_width=True,
            disabled=True,
        )

    st.sidebar.divider()

    service = st.session_state.get("service")
    if service:
        online = st.session_state.get("db_online", True)
        crm_ok = st.session_state.get("db_crm_ok", True)
        if online and crm_ok:
            st.sidebar.caption("🟢 База данных: подключена")
        elif online:
            st.sidebar.caption("🟡 Radar: OK · CRM: нет связи")
        else:
            st.sidebar.caption("🔴 База данных: нет связи")

        if st.sidebar.button("↻ Переподключить БД", use_container_width=True):
            result = check_and_reconnect(service)
            apply_health_to_session(result)
            st.rerun()

    if st.session_state.get("db_warn"):
        st.sidebar.warning(st.session_state.db_warn)

    if "nav_page" not in st.session_state:
        st.session_state.nav_page = "objects"
    return st.session_state.get("nav_page", "objects")
