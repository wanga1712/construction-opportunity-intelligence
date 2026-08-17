"""Lazy stage dispatcher for the real procurement card workspace."""
from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from src.ui.components.analytics_v2 import tabs as _tabs

_STAGES = (
    "Лиды",
    "Подготовка к торгам",
    "Идут торги",
    "Комиссия",
    "На рассмотрении",
    "Разыгранные",
)


def _renderer_for(stage: str) -> Callable[[], None] | None:
    renderers = {
        "Лиды": getattr(_tabs, "render_card_feed", None),
        "Идут торги": getattr(_tabs, "_render_torgi_tab", None),
        "Комиссия": getattr(_tabs, "_render_komissia_tab", None),
        "На рассмотрении": getattr(_tabs, "_render_review_tab", None),
        "Разыгранные": getattr(_tabs, "_render_razygranye_tab", None),
    }
    return renderers.get(stage)


def render_tabs() -> None:
    """Render only the selected stage; never build every real-card list."""
    stage = st.radio(
        "Раздел",
        options=_STAGES,
        horizontal=True,
        key="analytics_v2_active_stage",
        label_visibility="collapsed",
    )
    if stage == "Подготовка к торгам":
        st.info("Раздел будет подключён на следующем этапе")
        return

    renderer = _renderer_for(stage)
    if renderer is None:
        st.warning(f"Раздел «{stage}» недоступен в текущей сборке.")
        return
    renderer()
