"""Stable DOM keys shared by the waterproofing board and its drag-drop component."""
from __future__ import annotations

from hashlib import sha1
from typing import Any


def kanban_card_key(funnel: str, card_key: Any) -> str:
    """CSS-safe container key for one card on a named funnel."""
    digest = sha1(str(card_key or "").encode("utf-8")).hexdigest()[:16]
    return f"hydro_card_{funnel}_{digest}"


def kanban_column_key(board_key: str, stage: str) -> str:
    """CSS-safe container key for one stage column."""
    return f"{board_key}_col_{stage}"


__all__ = ["kanban_card_key", "kanban_column_key"]
