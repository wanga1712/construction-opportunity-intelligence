"""Streamlit CRM — настройка компаний.



Запуск:

    streamlit run app.py --server.port 8502



Порт 8502 (8501 занят генератором ТКП).

"""

import sys

from datetime import timedelta

from pathlib import Path

from typing import Optional



_PROJECT_ROOT = Path(__file__).resolve().parent

if str(_PROJECT_ROOT) not in sys.path:

    sys.path.insert(0, str(_PROJECT_ROOT))



from src.bootstrap import setup_source_path



setup_source_path()



import streamlit as st



from src.services.companies_service import CompaniesService

from src.services.db_bootstrap import connect_databases

from src.ui.db_health_ui import (

    apply_health_to_session,

    check_and_reconnect,

    render_db_status_banner,

)

from src.ui.ai_review_page import render_ai_review_page
from src.ui.analytics_contour_page import render_analytics_contour_page
from src.ui.analytics_contour_copy_page import render_analytics_contour_copy_page
from src.ui.analytics_contour_v2_page import render_analytics_contour_v2_page
from src.ui.v3_analytics_page import render_v3_analytics_page
from src.ui.companies_page import render_companies_page
from src.ui.computers_page import render_computers_page
from src.ui.customers_page import render_customers_page
from src.ui.export_queue_page import render_export_queue_page
from src.ui.infrastructure_page import render_infrastructure_page
from src.ui.system_health_page import render_system_health_page
from src.ui.map_page import render_map_page
from src.ui.opportunity_radar_page import render_opportunity_radar_page
from src.ui.waterproofing_page import render_waterproofing_page
from src.ui.crm_profiles_page import render_crm_profiles_page
from src.ui.nav import render_sidebar_nav
from src.ui.styles import inject_global_styles



DB_WATCH_INTERVAL_SEC = 20





def _render_startup_error(warn: str) -> None:
    st.error(warn or "Не удалось подключиться к базе данных.")
    st.markdown(
        "**Что проверить:**\n"
        "1. В `.env`: `DOM_RF_RADAR_DB_HOST`, `TENDER_MONITOR_DB_HOST`, `CRM_DB_HOST` → `10.8.0.7`\n"
        "2. С ноутбука: VPN/сеть до `10.8.0.7:5432`\n"
        "3. На сервере БД: `pg_hba.conf` разрешает ваш IP\n"
        "4. CRM на сервере: [http://10.8.0.13:8504/](http://10.8.0.13:8504/) — если там работает, "
        "проблема только в локальном `.env`/сети ноутбука"
    )
    if st.button("↻ Повторить подключение", key="startup_retry_db"):
        for key in ("service", "objects_service"):
            st.session_state.pop(key, None)
        st.rerun()


def _create_service() -> Optional[CompaniesService]:
    radar_db, tender_db, crm_db, warn = connect_databases()

    if not radar_db:
        _render_startup_error(warn)
        return None



    service = CompaniesService(radar_db=radar_db, tender_db=tender_db, crm_db=crm_db)

    with st.spinner("Загрузка закупочного контура…"):

        if not service.load_sync():

            st.error(service.last_error or "Ошибка загрузки")

            return None



    st.session_state.service = service

    st.session_state.db_warn = warn

    st.session_state.db_online = True

    st.session_state.db_crm_ok = crm_db.is_connected() if crm_db else True

    return service





def _get_service() -> Optional[CompaniesService]:

    if "service" not in st.session_state:

        return _create_service()



    service: CompaniesService = st.session_state.service

    result = check_and_reconnect(service)

    apply_health_to_session(result)

    return service





@st.fragment(run_every=timedelta(seconds=DB_WATCH_INTERVAL_SEC))

def _db_connection_watchdog() -> None:

    """Фоновая проверка сети — переподключение без действий пользователя."""

    service = st.session_state.get("service")

    if not service:

        return

    result = check_and_reconnect(service)

    apply_health_to_session(result)

    if st.session_state.get("db_just_reconnected"):

        st.rerun()





def main() -> None:

    st.set_page_config(

        page_title="CRM Система",

        page_icon="🏢",

        layout="wide",

        initial_sidebar_state="expanded",

    )

    inject_global_styles()

    _db_connection_watchdog()



    page = render_sidebar_nav()



    service = _get_service()

    if not service:

        st.stop()



    render_db_status_banner()



    if page == "ai_review":
        render_ai_review_page(service)
    elif page == "companies":

        render_companies_page(service)

    elif page == "objects":
        # Deprecated nav item removed; route kept for object_detail deep-links.
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

        render_system_health_page(service)

    elif page == "customers":

        render_customers_page()

    elif page == "export_pdf":

        render_export_queue_page(service)

    elif page == "crm_profiles":

        render_crm_profiles_page(service)

    else:

        st.info("Раздел в разработке.")





if __name__ == "__main__":

    main()


