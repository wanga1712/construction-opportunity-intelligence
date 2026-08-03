"""AI-review для вкладки аналитики."""
from __future__ import annotations

import streamlit as st


@st.fragment
def render_ai_review(rows):
    """Редактор AI-исправлений менеджера."""
    if rows.empty:
        st.info("Нет данных для AI-проверки.")
        return
    edited = st.data_editor(
        rows,
        hide_index=True,
        use_container_width=True,
        column_config={
            "confirmed": st.column_config.CheckboxColumn("Верно"),
            "confidence": st.column_config.ProgressColumn(
                "Уверенность AI", min_value=0.0, max_value=1.0
            ),
            "corrected_category": st.column_config.TextColumn(
                "Исправленная категория"
            ),
            "manager_comment": st.column_config.TextColumn("Комментарий"),
        },
        key="analytics_ai_review_editor",
    )
    st.session_state["pending_ai_corrections"] = edited.to_dict("records")
