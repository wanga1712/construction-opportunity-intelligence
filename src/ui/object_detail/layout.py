"""Streamlit layout helpers for object detail."""
from __future__ import annotations

import html
from typing import Dict, List, Optional

import streamlit as st

from modules.crm.analytics.object_classifier import segment_label
from .formatters import _FIELD_ICONS, _METRIC_ICONS, _SECTION_ICONS, _SEGMENT_ICONS


def _compact_metrics(
    items: List[tuple[str, str]],
    cols: int | None = None,
    *,
    icons: Dict[str, str] | None = None,
) -> None:
    """Компактные показатели без гигантских цифр Streamlit metric."""
    icon_map = icons or _METRIC_ICONS
    n = cols or len(items)
    columns = st.columns(n)
    for col, (label, value) in zip(columns, items):
        with col:
            icon = icon_map.get(label, "▪️")
            if label == "Сегмент" and value != "—":
                for key, seg_icon in _SEGMENT_ICONS.items():
                    if segment_label(key) == value or key in value.lower():
                        icon = seg_icon
                        break
            st.markdown(
                f'<div class="sf-metric">'
                f'<div class="sf-metric-label">'
                f'<span class="sf-ico">{icon}</span>{html.escape(label)}</div>'
                f'<div class="sf-metric-value">{html.escape(str(value))}</div>'
                f"</div>",
                unsafe_allow_html=True,
            )


def _section_title(text: str, icon: str | None = None) -> None:
    ico = icon or _SECTION_ICONS.get(text, "")
    prefix = f'<span class="sf-section-ico">{ico}</span>' if ico else ""
    st.markdown(
        f'<div class="sf-section-title">{prefix}{html.escape(text)}</div>',
        unsafe_allow_html=True,
    )


def _sf_fields(fields: List[tuple[str, Optional[str]]], cols: int = 2) -> None:
    """Двухколоночная сетка полей в стиле Salesforce record page."""
    visible = [(lbl, val) for lbl, val in fields if val and str(val).strip() and str(val) != "—"]
    if not visible:
        st.caption("Нет данных")
        return
    rows = [visible[i : i + cols] for i in range(0, len(visible), cols)]
    for row in rows:
        columns = st.columns(cols)
        for col, (label, value) in zip(columns, row):
            with col:
                field_icon = _FIELD_ICONS.get(label, "")
                icon_html = f'<span class="sf-ico">{field_icon}</span>' if field_icon else ""
                st.markdown(
                    f'<div class="sf-field">'
                    f'<div class="sf-field-label">{icon_html}{html.escape(label)}</div>'
                    f'<div class="sf-field-value">{html.escape(str(value))}</div>'
                    f"</div>",
                    unsafe_allow_html=True,
                )
        if len(row) < cols:
            break
