"""Streamlit rendering and state adapter for database health checks."""
import streamlit as st

from src.services.db_health import DbHealthResult, check_and_reconnect as _check_and_reconnect


def check_and_reconnect(service) -> DbHealthResult:
    return _check_and_reconnect(
        service, previously_online=st.session_state.get("db_online", True),
    )


def apply_health_to_session(result: DbHealthResult) -> None:
    previously_online = st.session_state.get("db_online", True)
    st.session_state.db_online = result.radar_ok
    st.session_state.db_crm_ok = result.crm_ok
    if previously_online and not result.radar_ok:
        st.session_state.db_status_message = "Соединение с базой потеряно. Переподключение каждые 20 сек…"
    elif not previously_online and result.radar_ok:
        st.session_state.db_status_message = ""
        st.session_state.db_just_reconnected = True
    elif result.radar_ok:
        st.session_state.db_status_message = ""


def render_db_status_banner() -> None:
    if st.session_state.pop("db_just_reconnected", False):
        st.success("Соединение с базой восстановлено. Можно продолжать работу.")
    if not st.session_state.get("db_online", True):
        st.warning(st.session_state.get(
            "db_status_message",
            "Нет связи с базой Radar. Переподключение выполняется автоматически.",
        ))
