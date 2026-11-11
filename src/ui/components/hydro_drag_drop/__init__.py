"""Streamlit bridge for native drag-and-drop on the waterproofing kanban."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components

_COMPONENT_DIR = Path(__file__).resolve().parent
_hydro_drag_drop = components.declare_component(
    "hydro_drag_drop",
    path=str(_COMPONENT_DIR),
)


def hydro_drag_drop(
    *,
    cards: list[dict[str, Any]],
    columns: list[dict[str, Any]],
    key: str,
) -> dict[str, Any] | None:
    """Enable native card dragging and return the latest drop event."""
    return _hydro_drag_drop(
        cards=cards,
        columns=columns,
        key=key,
        default=None,
    )


__all__ = ["hydro_drag_drop"]
