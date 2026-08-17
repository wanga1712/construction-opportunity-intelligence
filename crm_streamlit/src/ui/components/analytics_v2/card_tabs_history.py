"""Helper to render History tab in CRM compact card."""
import streamlit as st
import json
from datetime import datetime

def render_history_tab(crm_db, procurement_id: int) -> None:
    st.markdown("### 📜 История ручных и ИИ правок")
    
    try:
        history = crm_db.execute_query(
            """
            SELECT action_type, user_name, comment, timestamp, approved_for_training, changed_fields
            FROM crm_manual_assessments_audit
            WHERE procurement_id = %s
            ORDER BY timestamp DESC
            """,
            (procurement_id,)
        )
    except Exception as e:
        st.error(f"Ошибка загрузки истории изменений: {e}")
        return

    if not history:
        st.info("История изменений пуста.")
        return

    for h in history:
        t_str = h["timestamp"].strftime("%d.%m.%Y %H:%M") if isinstance(h["timestamp"], datetime) else str(h["timestamp"])
        action = h["action_type"]
        user = h["user_name"]
        comment = h["comment"] or "Без комментария"
        approved = "✅ Утверждено для обучения" if h["approved_for_training"] else "⏳ Ожидает проверки"
        
        st.markdown(
            f'<div style="background:#f8fafc; border-left: 3px solid #64748b; padding: 10px; margin-bottom: 8px; border-radius: 4px;">'
            f'<div style="display:flex; justify-content:space-between; font-size:11px; color:#64748b;">'
            f'<span>👤 <b>{user}</b> ({action})</span>'
            f'<span>📅 {t_str}</span>'
            f'</div>'
            f'<div style="font-size:13px; margin-top:4px; color:#1e293b;">{comment}</div>'
            f'<div style="font-size:11px; margin-top:4px; color:#475569;">Статус: <i>{approved}</i></div>'
            f'</div>',
            unsafe_allow_html=True
        )

