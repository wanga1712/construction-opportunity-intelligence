"""Streamlit CRM application bootstrap (routing + session dependencies).

Root ``app.py`` only configures the page and calls ``main()`` here.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

import streamlit as st

from src.services.companies_service import CompaniesService
from src.services.db_bootstrap import connect_databases
from src.ui.ai_review_page import render_ai_review_page
from src.ui.analytics_contour_copy_page import render_analytics_contour_copy_page
from src.ui.analytics_contour_page import render_analytics_contour_page
from src.ui.analytics_contour_v2_page import render_analytics_contour_v2_page
from src.ui.category_registry_page import render_category_registry_page
from src.ui.companies_page import render_companies_page
from src.ui.computers_page import render_computers_page
from src.ui.crm_profiles_page import render_crm_profiles_page
from src.ui.customers_page import render_customers_page
from src.ui.db_health_ui import (
    apply_health_to_session,
    check_and_reconnect,
    render_db_status_banner,
)
from src.ui.export_queue_page import render_export_queue_page
from src.ui.infrastructure_page import render_infrastructure_page
from src.ui.map_page import render_map_page
from src.ui.nav import render_sidebar_nav
from src.ui.opportunity_radar_page import render_opportunity_radar_page
from src.ui.page_deps import (
    PageDependency,
    page_dependency,
    requires_companies_load_sync,
    requires_companies_service,
)
from src.ui.system_health_page import render_system_health_page
from src.ui.v3_analytics_page import render_v3_analytics_page
from src.ui.waterproofing_page import render_waterproofing_page

DB_WATCH_INTERVAL_SEC = 20


def _render_startup_error(warn: str) -> None:
    st.error(warn or "Не удалось подключиться к базе данных.")
    st.markdown(
        "**Что проверить:**\n"
        "1. В `.env`: `DOM_RF_RADAR_DB_HOST`, `TENDER_MONITOR_DB_HOST`, `CRM_DB_HOST`\n"
        "2. VPN/сеть до БД\n"
        "3. На сервере БД: `pg_hba.conf` разрешает ваш IP\n"
    )
    if st.button("↻ Повторить подключение", key="startup_retry_db"):
        for key in ("service", "objects_service"):
            st.session_state.pop(key, None)
        st.rerun()


def _create_service(*, load_companies: bool = True) -> Optional[CompaniesService]:
    radar_db, tender_db, crm_db, warn = connect_databases()
    if load_companies and not radar_db:
        _render_startup_error(warn)
        return None
    if not load_companies and not any((radar_db, tender_db, crm_db)):
        _render_startup_error(warn)
        return None

    service = CompaniesService(radar_db=radar_db, tender_db=tender_db, crm_db=crm_db)
    if load_companies:
        with st.spinner("Загрузка закупочного контура…"):
            if not service.load_sync():
                st.error(service.last_error or "Ошибка загрузки")
                return None

    st.session_state.service = service
    st.session_state.db_warn = warn
    st.session_state.db_online = bool(radar_db) if radar_db is not None else True
    st.session_state.db_crm_ok = crm_db.is_connected() if crm_db else True
    st.session_state.companies_data_loaded = bool(load_companies)
    return service


def _get_service(*, load_companies: bool = True, ping: bool = False) -> Optional[CompaniesService]:
    """Return session CompaniesService.

    ``ping=False`` (default): do not synchronously probe DBs on navigation —
    the 20s watchdog owns reconnect. Existing healthy service is returned as-is.
    """
    if "service" not in st.session_state:
        return _create_service(load_companies=load_companies)

    service: CompaniesService = st.session_state.service
    if load_companies and not st.session_state.get("companies_data_loaded"):
        with st.spinner("Загрузка закупочного контура…"):
            if not service.load_sync():
                st.error(service.last_error or "Ошибка загрузки")
                return None
        st.session_state.companies_data_loaded = True

    if ping:
        result = check_and_reconnect(service)
        apply_health_to_session(result)
    return service


@st.fragment(run_every=timedelta(seconds=DB_WATCH_INTERVAL_SEC))
def _db_connection_watchdog() -> None:
    """Background DB recovery — only when a service already exists."""
    service = st.session_state.get("service")
    if not service:
        return
    result = check_and_reconnect(service)
    apply_health_to_session(result)
    if st.session_state.get("db_just_reconnected"):
        st.rerun()


def _render_page(page: str, service: Optional[CompaniesService]) -> None:
    if page == "ai_review":
        render_ai_review_page(service)
    elif page == "companies":
        render_companies_page(service)
    elif page == "objects":
        render_analytics_contour_page(service)
    elif page == "objects_copy":
        render_analytics_contour_copy_page(service)
    elif page == "objects_v2":
        render_analytics_contour_v2_page(service)
    elif page == "analytics_v3":
        render_v3_analytics_page(service)
    elif page == "opportunity_radar":
        render_opportunity_radar_page(service)
    elif page == "computers":
        render_computers_page(service)
    elif page == "waterproofing":
        render_waterproofing_page(service)
    elif page == "map":
        render_map_page(service)
    elif page == "infrastructure":
        render_infrastructure_page(service)
    elif page == "system_health":
        render_system_health_page(None)
    elif page == "customers":
        render_customers_page()
    elif page == "export_pdf":
        render_export_queue_page(service)
    elif page == "crm_profiles":
        render_crm_profiles_page(None)
    elif page == "category_registry":
        render_category_registry_page(service)
    else:
        st.info("Раздел в разработке.")


def main() -> None:
    page = render_sidebar_nav()
    dep = page_dependency(page)

    # Fast path: snapshot / non-Companies pages — no load_sync, no Radar designers.
    if dep == PageDependency.NO_SERVICE:
        _render_page(page, None)
        return

    if dep in (PageDependency.OTHER, PageDependency.CRM_DB_ONLY):
        # Need DB handles (or parking) but NOT CompaniesService.load_sync.
        service = _get_service(load_companies=False, ping=False)
        if dep == PageDependency.CRM_DB_ONLY and not service:
            st.stop()
        if dep == PageDependency.OTHER and page == "infrastructure" and not service:
            st.stop()
        if service is not None:
            _db_connection_watchdog()
            render_db_status_banner()
        _render_page(page, service)
        return

    # COMPANIES_SERVICE pages
    _db_connection_watchdog()
    service = _get_service(load_companies=True, ping=False)
    if not service:
        st.stop()
    render_db_status_banner()
    _render_page(page, service)


# Re-exports for tests that patch bootstrap symbols.
__all__ = [
    "main",
    "_get_service",
    "_create_service",
    "_db_connection_watchdog",
    "requires_companies_service",
    "requires_companies_load_sync",
]
