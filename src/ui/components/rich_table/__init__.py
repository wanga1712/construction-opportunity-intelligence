"""Streamlit-компонент: рисует готовую HTML-таблицу и ловит клик по строке.

Позволяет сохранить богатую HTML-таблицу (бар окна, цвета медалей, статусы) и
при этом получить клик по `<tr data-pid="...">` без галочек/checkbox-колонок.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import streamlit.components.v1 as components

_COMPONENT_DIR = Path(__file__).resolve().parent
_rich_table = components.declare_component("rich_table", path=str(_COMPONENT_DIR))


def rich_table(html: str, *, css: str = "", height: int = 640,
               key: Optional[str] = None) -> Optional[str]:
    """Вернуть `data-pid` строки, по которой кликнули (иначе None)."""
    return _rich_table(html=html, css=css, height=height, key=key, default=None)
