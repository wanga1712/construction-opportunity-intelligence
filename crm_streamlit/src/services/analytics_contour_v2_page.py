"""Страница аналитического контура v2."""
from __future__ import annotations

import streamlit as st

from src.services.object_subcategory_links import load_links_map
from src.services.product_subcategories_service import load_filter_options
from src.ui.session_deps import get_objects_service
from src.ui.components.analytics_v2.analytics_expander import render_analytics_expander
from src.ui.components.analytics_v2.header import render_header
from src.ui.components.analytics_v2.kpi_row import render_kpi_row
from src.ui.components.analytics_v2.limits import render_limits
from src.ui.components.analytics_v2.quick_filters import render_quick_filters
from src.ui.components.analytics_v2.sidebar import render_sidebar
from src.ui.components.analytics_v2.tabs import render_tabs


def _build_v2_cards(service) -> list[dict]:
    """Собираем реальные карточки v2 из текущего контура объектов."""
    objects_service = get_objects_service(service, cache_key="objects_service_v2")
    if not objects_service.load_sync():
        return []
    items = objects_service.all_objects()
    links_map = load_links_map(getattr(service, "crm_db", None), [item.key for item in items], contour_code="procurement")

    selected_header = st.session_state.get("analytics_v2_subcategory", "Все подкатегории")
    selected_sidebar = set(st.session_state.get("analytics_v2_sidebar_subcategories", []))
    cards: list[dict] = []
    for item in items:
        links = links_map.get(item.key, [])
        labels = [f'{row.get("category_name")} / {row.get("subcategory_name")}' for row in links if row.get("category_name") and row.get("subcategory_name")]
        if selected_header != "Все подкатегории" and selected_header not in labels:
            continue
        if selected_sidebar and not selected_sidebar.intersection(labels):
            continue
        cards.append(
            {
                "level": (item.quality_tier or "wood").capitalize(),
                "object_type": item.segment or "other",
                "region": item.region or item.address or "Не найдено в БД",
                "title": item.name or "Не найдено в БД",
                "stage": item.pipeline_stage_label or "Не найдено в БД",
                "category": ", ".join(labels) if labels else "Не найдено в БД",
                "material": ", ".join(item.matched_product_preview[:3]) or "Не найдено в БД",
                "volume": item.docs_volume_preview or "Не найдено в БД",
                "next_step": item.ai_manager_next_step or "Не найдено в БД",
                "customer": item.balance_holder or item.customer_name or "Не найдено в БД",
                "designer": item.expertise_planner or item.expertise_developer or "Не найдено в БД",
                "contractor": item.contractor_name or "Не найдено в БД",
                "updated_at": str(item.delivery_end_date or item.end_date or item.start_date or "Не найдено в БД")[:10],
                "rating_reason": item.ai_card_status_reason or item.ai_priority_reason or "Не найдено в БД",
                "found_summary": ", ".join(item.matched_product_preview[:4]) or "Не найдено в БД",
                "subcategory_links": links,
            }
        )
    st.session_state["analytics_v2_cards"] = cards
    return cards


def render_analytics_contour_v2_page(service) -> None:
    """Рисуем v2 и подгружаем подкатегории из CRM БД."""
    options = load_filter_options(getattr(service, "crm_db", None), contour_code="procurement")
    st.session_state["analytics_v2_subcategory_options"] = options
    render_sidebar(options)
    render_header(options)
    _build_v2_cards(service)
    render_kpi_row()
    render_limits()
    render_quick_filters()
    render_tabs()
    render_analytics_expander()
