"""KPI и лимиты нового аналитического контура."""
from __future__ import annotations

import streamlit as st


def render_kpi(metrics: dict) -> None:
    """Верхняя строка KPI."""
    cols = st.columns(len(metrics))
    for idx, (label, value) in enumerate(metrics.items()):
        with cols[idx]:
            st.metric(label, value, border=True)


def render_limits(limits: dict) -> None:
    """Компактный контейнер лимитов."""
    with st.container(border=True):
        st.markdown("**Лимиты карточек**")
        cols = st.columns(4)
        order = [
            ("gold", "Gold"),
            ("silver", "Silver"),
            ("bronze", "Bronze"),
            ("early", "Early"),
        ]
        for idx, (code, label) in enumerate(order):
            item = limits[code]
            with cols[idx]:
                st.caption(f"{label}: {item['used']} / {item['limit']}")
                total = item["limit"]
                used = item["used"]
                st.progress(min(used / total, 1.0) if total else 0.0)
