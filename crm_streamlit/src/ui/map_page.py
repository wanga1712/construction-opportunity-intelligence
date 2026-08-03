"""CRM map page: cadastral parking objects + tender layers."""
from __future__ import annotations

import streamlit as st

from src.services.map_export import fetch_map_stats
from src.services.map_layers_service import LAYER_COLORS, LAYER_LABELS, build_map_geojson
from src.ui.session_deps import get_parking_db
from src.ui.map_view import render_map

_ALL_LAYERS = ("nspd", "nashdom", "44fz", "223fz", "615pp")

_UK_FILTER_OPTIONS = {
    "Только с УК / ответственным контуром": "DONE",
    "Без УК": "NO_UK",
    "Все объекты": "ALL",
}
def render_map_page(service) -> None:
    st.title("Карта объектов")
    st.caption(
        "Кадастр/паркинги, NashDom и закупки на одной карте. "
        "Для паркингов пиктограмма и цвет показывают гидро-приоритет объекта."
    )

    parking_db = get_parking_db()
    if parking_db.connect():
        stats = fetch_map_stats(parking_db)
        if stats:
            u1, u2, u3, u4 = st.columns(4)
            u1.metric("НСПД с УК", stats.get("with_uk", 0))
            u2.metric("УК не найдена", stats.get("uk_not_found", 0))
            u3.metric("Ожидают обогащения", stats.get("pending", 0))
            u4.metric("С координатами", stats.get("with_coords", 0))

            g1, g2, g3, g4 = st.columns(4)
            g1.metric("A: нежилые с подземкой", stats.get("grade_a", 0))
            g2.metric("B: МКД ≥2 подз.", stats.get("grade_b", 0))
            g3.metric("C: подземка / проверить", stats.get("grade_c", 0))
            g4.metric("D: слабый сигнал", stats.get("grade_d", 0))

    st.markdown("#### Слои данных")
    cols = st.columns(len(_ALL_LAYERS))
    defaults = {
        "nspd": True,
        "nashdom": False,
        "44fz": False,
        "223fz": False,
        "615pp": False,
    }
    layers = {}
    for col, key in zip(cols, _ALL_LAYERS):
        color = LAYER_COLORS[key]
        with col:
            layers[key] = st.checkbox(
                LAYER_LABELS[key],
                value=st.session_state.get(f"map_layer_{key}", defaults[key]),
                key=f"map_layer_{key}",
            )
            st.markdown(
                f'<span style="display:inline-block;width:12px;height:12px;'
                f'border-radius:50%;background:{color};"></span>',
                unsafe_allow_html=True,
            )

    st.markdown("#### Фильтры")
    f1, f2, f3 = st.columns([1.2, 1.2, 1])
    with f1:
        uk_label = st.selectbox(
            "НСПД: управляющая компания",
            list(_UK_FILTER_OPTIONS.keys()),
            index=0,
            key="map_uk_filter_label",
            help="DONE — объект привязан к УК/ТСЖ/ответственному контуру.",
        )
        uk_status = _UK_FILTER_OPTIONS[uk_label]
    with f2:
        min_floors = st.selectbox(
            "НСПД: подземные этажи",
            [0, 1, 2, 3],
            format_func=lambda x: "Любые" if x == 0 else f"≥ {x}",
            key="map_page_min_floors",
        )
    with f3:
        st.button("↻ Обновить карту", key="map_page_reload", use_container_width=True)

    active = {k for k, v in layers.items() if v}
    if not active:
        st.warning("Включите хотя бы один слой.")
        return

    if "nspd" in active and parking_db and not parking_db.connect():
        st.error(f"НСПД: нет подключения к БД паркинга — {parking_db.last_error}")

    with st.spinner("Загрузка точек…"):
        geojson, stats = build_map_geojson(
            active_layers=active,
            parking_db=parking_db if "nspd" in active else None,
            radar_db=service.radar_db,
            crm_db=service.crm_db,
            min_floors=min_floors,
            uk_status=uk_status if "nspd" in active else "ALL",
        )

    total = stats.get("total", 0)
    by_layer = stats.get("by_layer", {})
    mcols = st.columns(len(_ALL_LAYERS))
    for i, key in enumerate(_ALL_LAYERS):
        if key in active:
            mcols[i].metric(LAYER_LABELS[key], by_layer.get(key, 0))

    if stats.get("no_coords_tender"):
        st.info(
            f"⚠ {stats['no_coords_tender']} закупок без координат "
            "(нет привязки к NashDom/domrf_object_id)."
        )

    if total == 0:
        if uk_status == "DONE" and "nspd" in active:
            st.warning(
                "Нет объектов с найденной УК по выбранным фильтрам. "
                "Попробуйте «Все объекты» или уменьшите фильтр по подземным этажам."
            )
        else:
            st.warning("Нет точек для выбранных слоёв.")
        return

    st.caption(
        "Легенда НСПД: 🏢 A — нежилые с подземкой, "
        "🏘️ B — МКД с ≥2 подземными этажами, 🅿️ C — подземка/проверить."
    )
    st.caption(f"На карте: **{total}** объектов")
    render_map(geojson, zoom=11)

