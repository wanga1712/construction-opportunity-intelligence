"""Category Opportunity UI Section Component.

Renders '🎯 НАЙДЕНО ПОСЛЕ ИССЛЕДОВАНИЯ' section on procurement cards and detail views,
displaying multi-category confirmed commercial opportunities with medal badges,
quantity aggregations, potential supply value derivation, and evidence drilldowns.
"""

from __future__ import annotations

from typing import List, Optional, Tuple
import streamlit as st
from src.services.category_opportunity_service import (
    CategoryOpportunity,
    RELATION_DISPLAY,
)

MEDAL_EMOJI = {
    'GOLD': '🥇 GOLD',
    'SILVER': '🥈 SILVER',
    'BRONZE': '🥉 BRONZE',
    'WOOD': '🪵 WOOD',
    'UNASSIGNED': '⚪ UNASSIGNED',
}

MEDAL_COLOR = {
    'GOLD': '#FFD700',
    'SILVER': '#C0C0C0',
    'BRONZE': '#CD7F32',
    'WOOD': '#8B5A2B',
    'UNASSIGNED': '#808080',
}


def format_supply_value(val_rub: Optional[float], method: str) -> Tuple[str, str]:
    """Format supply value in RUB and return descriptive badge string."""
    if val_rub is None or method == "NOT_AVAILABLE":
        return "—", "Недоступно"

    val_formatted = f"{val_rub:,.0f} ₽".replace(",", " ")
    
    if method == "EXPLICIT_LINE_TOTAL":
        return val_formatted, "Явная сумма строк"
    elif method == "DIRECT_SINGLE_CATEGORY_NMCK_UPPER_BOUND":
        return val_formatted, "Верхняя оценка (НМЦК)"
    else:
        return val_formatted, method


def render_category_opportunity_section(
    opportunities: List[CategoryOpportunity],
    title: str = "🎯 НАЙДЕНО ПОСЛЕ ИССЛЕДОВАНИЯ",
    show_filters: bool = False,
):
    """Render category opportunities section in Streamlit UI."""
    if not opportunities:
        return

    st.markdown(f"### {title}")

    # Optional local filters
    displayed_opps = opportunities
    if show_filters and len(opportunities) > 1:
        col_cat, col_med = st.columns(2)
        with col_cat:
            cats = ["Все категории"] + list({o.category_name for o in opportunities})
            sel_cat = st.selectbox("Фильтр по категории", cats, key=f"opp_cat_filter_{opportunities[0].procurement_id}")
            if sel_cat != "Все категории":
                displayed_opps = [o for o in displayed_opps if o.category_name == sel_cat]
        with col_med:
            medals = ["Все медали"] + list({o.commercial_medal for o in opportunities})
            sel_med = st.selectbox("Фильтр по медали", medals, key=f"opp_med_filter_{opportunities[0].procurement_id}")
            if sel_med != "Все медали":
                displayed_opps = [o for o in displayed_opps if o.commercial_medal == sel_med]

    for opp in displayed_opps:
        render_category_opportunity_card(opp)


def render_category_opportunity_card(opp: CategoryOpportunity):
    """Render a single category opportunity subcard."""
    medal_label = MEDAL_EMOJI.get(opp.commercial_medal, opp.commercial_medal)
    relation_label = RELATION_DISPLAY.get(opp.product_relation, opp.product_relation)
    val_str, method_badge = format_supply_value(opp.potential_supply_value_rub, opp.potential_supply_value_method)

    with st.container(border=True):
        head_col1, head_col2 = st.columns([3, 1])
        with head_col1:
            st.markdown(f"#### 🏷️ **{opp.category_name}**")
            if opp.subcategory_name and opp.subcategory_name != opp.category_id:
                st.caption(f"Подкатегория: `{opp.subcategory_name}`")
        with head_col2:
            st.markdown(f"### **{medal_label}**")

        st.caption(f"🔗 Связь с закупкой: **{relation_label}** | Статус: `{opp.commercial_state}`")

        # Quantities & Potential value metrics
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Уникальных материалов", opp.material_count)
        with m2:
            st.metric("Позиций в документах", opp.position_count)
        with m3:
            qty_summary = ", ".join([f"{u['quantity']:,.1f} {u['unit']}".replace(",", " ") for u in opp.quantities_by_unit]) or "—"
            st.metric("Общий объем", qty_summary)
        with m4:
            st.metric("Потенциал поставки", val_str, help=f"Метод расчета: {method_badge}")

        # Expandable evidence details
        if opp.confirmed_materials:
            with st.expander(f"🔍 Доказательная база ({opp.material_count} мат. / {opp.evidence_count} упом.)"):
                for idx, mat in enumerate(opp.confirmed_materials, 1):
                    mat_name = mat.get('material_name', '')
                    page = mat.get('page_or_sheet', '')
                    row = mat.get('row_number', '')
                    context = mat.get('context', '')
                    
                    loc_info = []
                    if page:
                        loc_info.append(f"стр./лист `{page}`")
                    if row:
                        loc_info.append(f"строка `{row}`")
                    loc_str = f" ({', '.join(loc_info)})" if loc_info else ""
                    
                    st.markdown(f"**{idx}. {mat_name}**{loc_str}")
                    if context:
                        st.caption(f"📝 *«...{context}...»*")
