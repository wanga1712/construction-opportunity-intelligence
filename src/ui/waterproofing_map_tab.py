"""Map tab for waterproofing CRM."""
from __future__ import annotations

import streamlit as st

from src.services.map_layers_service import LAYER_LABELS, build_map_geojson
from src.services.objects_service import ObjectsService
from src.ui.map_view import render_map
from src.ui.session_deps import get_parking_db


def render_map_tab(service: ObjectsService) -> None:
    """Render the shared map layers with waterproofing defaults."""
    st.caption("Карта использует уже существующие боевые слои: НСПД, NashDom и закупки из CRM-индекса.")
    parking_db = get_parking_db()
    c1, c2, c3 = st.columns(3)
    with c1:
        min_floors = st.selectbox(
            "НСПД: подземные этажи", [1, 2, 3, 0], index=0,
            format_func=lambda value: "Любые" if value == 0 else f"≥ {value}",
        )
    with c2:
        uk_status = st.selectbox(
            "УК", ["DONE", "ALL", "NO_UK"],
            format_func=lambda value: {"DONE": "Только с УК", "ALL": "Все", "NO_UK": "Без УК"}[value],
        )
    with c3:
        st.button("↻ Обновить карту", key="hydro_map_reload", use_container_width=True)

    if parking_db and not parking_db.connect():
        st.warning(f"НСПД недоступна: {parking_db.last_error}")
    with st.spinner("Загрузка карты…"):
        geojson, stats = build_map_geojson(
            active_layers={"nspd", "44fz", "223fz", "615pp"},
            parking_db=parking_db,
            radar_db=service.radar_db,
            crm_db=service.crm_db,
            min_floors=min_floors,
            uk_status=uk_status,
        )
    columns = st.columns(5)
    for index, layer in enumerate(("nspd", "44fz", "223fz", "615pp")):
        columns[index].metric(LAYER_LABELS.get(layer, layer), stats.get("by_layer", {}).get(layer, 0))
    columns[-1].metric("Всего точек", stats.get("total", 0))
    if not stats.get("total"):
        st.warning("Нет точек для выбранных фильтров.")
        return
    render_map(geojson, zoom=11)
