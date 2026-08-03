"""Objects tab for the waterproofing CRM page."""
from __future__ import annotations

import html

import streamlit as st

from src.services.companies_service import CompaniesService
from src.services.object_lifecycle import is_awarded
from src.services.object_models import ObjectViewItem
from src.services.objects_service import ObjectsService
from src.services.hydro_zone_profiles import HYDRO_ZONE_PROFILES, detect_hydro_zones, hydro_zone_labels
from src.services.waterproofing_scoring import candidate_objects, hydro_score, priority_letter
from src.ui.object_card_format import fmt_date
from src.ui.session_deps import get_objects_service


def render_object_row(item: ObjectViewItem) -> None:
    """Render one scored object card and preserve its navigation state keys."""
    score, reasons = hydro_score(item)
    active_badge = "🔥 новая / в работе" if not is_awarded(item) else "📦 разыграна"
    with st.container(border=True):
        c1, c2 = st.columns([4, 1])
        with c1:
            st.markdown(f"#### {html.escape(item.name or 'Объект')}")
            st.caption(" · ".join(filter(None, [
                item.address or item.region or "",
                item.status or "",
                f"Поставка: {fmt_date(item.delivery_start_date)} — {fmt_date(item.delivery_end_date)}"
                if item.delivery_start_date or item.delivery_end_date else "",
            ])))
            st.write(" · ".join(reasons))
            zone_labels = hydro_zone_labels(detect_hydro_zones(item))
            if zone_labels:
                st.caption("Зоны применимости: " + ", ".join(zone_labels))
            if item.ai_priority_reason:
                st.caption(f"AI: {item.ai_priority_reason}")
        with c2:
            st.metric("Hydro score", score)
            st.caption(priority_letter(score))
            st.info(active_badge)
            if st.button("Открыть карточку", key=f"hydro_open_{item.key}", use_container_width=True):
                st.session_state["object_detail_key"] = item.key
                st.session_state["nav_page"] = "objects"
                st.rerun()


def render_objects_tab(service: CompaniesService | ObjectsService) -> None:
    """Render CRM object metrics, filters, and scored candidate rows."""
    objects_service = get_objects_service(service, cache_key="waterproofing_objects_service")
    objects_service.load_sync()
    all_items = objects_service.all_objects()
    active_processed = [item for item in all_items if not is_awarded(item) and (item.doc_matches or item.matched_files)]
    hydro_candidates = candidate_objects(all_items, only_hydro=True)
    metrics = st.columns(4)
    for column, label, value in zip(metrics, (
        "Все объекты CRM", "Активные с документами", "Hydro-кандидаты", "Новые в приоритете",
    ), (len(all_items), len(active_processed), len(hydro_candidates),
        sum(1 for item in hydro_candidates if not is_awarded(item)))):
        column.metric(label, value)

    only_hydro = st.toggle("Показывать только похожие на гидроизоляцию", value=True)
    zone_options = ["Все зоны"] + [x.label for x in HYDRO_ZONE_PROFILES]
    selected_zone = st.selectbox("Зона применимости", zone_options, index=0, key="hydro_zone_filter")
    page_size = st.selectbox("На странице", [12, 24, 48, 96], index=1, key="hydro_page_size")
    items = candidate_objects(all_items, only_hydro=only_hydro)[:page_size]
    if selected_zone != "Все зоны":
        code_map = {x.label: x.code for x in HYDRO_ZONE_PROFILES}
        zone_code = code_map.get(selected_zone)
        items = [item for item in items if zone_code and zone_code in detect_hydro_zones(item)]
    st.caption("Сортировка: новые/неразыгранные с документами → Hydro score → AI priority → совпадения.")
    if not items:
        st.warning("Нет объектов по выбранному фильтру.")
        return
    for item in items:
        render_object_row(item)
