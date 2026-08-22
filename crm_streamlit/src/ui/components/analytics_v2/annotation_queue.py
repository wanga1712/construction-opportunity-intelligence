"""Invisible SAVE+NEXT queue for the current filtered card list.

Does not add tabs, labels, or chrome. After SAVE+NEXT the next card in the
current filtered list is rotated to the front and stays first across Streamlit
reruns until the expert advances again or the visible filter set changes.
"""
from __future__ import annotations

from typing import Any

GO_NEXT_KEY = "annotation_go_next"
GO_NEXT_FROM_KEY = "annotation_go_next_from"
QUEUE_PREFIX = "_annotation_queue_"
ACTIVE_QUEUE_KEY = "annotation_active_queue_session_key"


def remember_queue(card_ids: list[int], session_key: str, session: dict) -> None:
    session[QUEUE_PREFIX + session_key] = list(card_ids)


def next_id(card_ids: list[int], current_id: Any) -> int | None:
    if not card_ids:
        return None
    if current_id not in card_ids:
        return None
    idx = card_ids.index(current_id)
    if idx + 1 >= len(card_ids):
        return None
    return card_ids[idx + 1]


def rotate_to(cards: list[dict], target_id: Any) -> list[dict]:
    if target_id is None:
        return cards
    ids = [c.get("id") for c in cards]
    if target_id not in ids:
        return cards
    i = ids.index(target_id)
    return cards[i:] + cards[:i]


def bind_and_advance(
    cards: list[dict],
    session_key: str,
    session: dict,
    *,
    consume_if_missing: bool = True,
) -> list[dict]:
    """Advance SAVE+NEXT on the filter-sorted list, then keep the current card first."""
    ids = [c["id"] for c in cards]
    remember_queue(ids, session_key, session)

    if session.get(GO_NEXT_KEY):
        active_queue = session.get(ACTIVE_QUEUE_KEY)
        if active_queue and active_queue != session_key:
            return cards
        from_id = session.get(GO_NEXT_FROM_KEY)
        if from_id not in ids:
            if consume_if_missing:
                session.pop(GO_NEXT_KEY, None)
                session.pop(GO_NEXT_FROM_KEY, None)
        else:
            session.pop(GO_NEXT_KEY, None)
            session.pop(GO_NEXT_FROM_KEY, None)
            nxt = next_id(ids, from_id)
            session[session_key] = nxt if nxt is not None else from_id

    selected = session.get(session_key)
    if selected in ids:
        return rotate_to(cards, selected)
    return cards
