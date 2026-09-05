import streamlit as st
from src.learning.procurement_scope.classifier import ProcurementScopeType

def render_scope_badge(scope_type_val: str):
    badges = {
        ProcurementScopeType.DIRECT_GOODS.value: "🛒 ПРЯМАЯ ПОСТАВКА",
        ProcurementScopeType.WORKS_WITH_EMBEDDED_PRODUCTS.value: "🏗 РАБОТЫ / ОБЪЕКТ",
        ProcurementScopeType.DESIGN_PROJECT.value: "📐 ПРОЕКТИРОВАНИЕ",
        ProcurementScopeType.EQUIPMENT_AND_INSTALLATION.value: "⚙️ ПОСТАВКА + МОНТАЖ",
        ProcurementScopeType.SERVICE_WITH_CONSUMABLES.value: "🧰 УСЛУГА + РАСХОДНИКИ",
        ProcurementScopeType.PURE_SERVICE.value: "🧹 УСЛУГА",
        ProcurementScopeType.MIXED.value: "🔀 СМЕШАННАЯ ЗАКУПКА",
        ProcurementScopeType.UNKNOWN.value: "❓ НЕ ОПРЕДЕЛЕНО",
    }
    
    val = scope_type_val or ProcurementScopeType.UNKNOWN.value
    st.markdown(f"**{badges.get(val, badges[ProcurementScopeType.UNKNOWN.value])}**")
