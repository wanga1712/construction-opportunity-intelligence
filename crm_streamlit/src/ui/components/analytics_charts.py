"""Графики аналитики по текущей выборке."""
from __future__ import annotations

import plotly.express as px
import streamlit as st


def _pick(df, *names: str) -> str:
    """Берём первое доступное имя колонки из DataFrame."""
    for name in names:
        if name in df.columns:
            return name
    raise KeyError(f"Нет ни одной ожидаемой колонки: {names}")


def render_charts(stage_df, tier_df, category_df) -> None:
    """Компактные графики с поддержкой старой и новой схем колонок."""
    stage_x = _pick(stage_df, "Карточек", "count")
    stage_y = _pick(stage_df, "Стадия", "stage")
    tier_names = _pick(tier_df, "Уровень", "tier")
    tier_values = _pick(tier_df, "Карточек", "count")
    category_x = _pick(category_df, "Категория", "category")
    category_y = _pick(category_df, "Карточек", "count")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**По стадиям**")
        fig = px.bar(stage_df, x=stage_x, y=stage_y, orientation="h", text=stage_x)
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    with c2:
        st.markdown("**По уровням**")
        fig = px.pie(tier_df, names=tier_names, values=tier_values, hole=0.65)
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    with c3:
        st.markdown("**По категориям**")
        fig = px.bar(category_df, x=category_x, y=category_y, text=category_y)
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
