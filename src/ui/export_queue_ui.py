"""Streamlit session-state adapter for the pure PDF-export queue."""
from typing import List, Set

import streamlit as st

from src.services import export_queue

_QUEUE_KEY = "pdf_export_queue"
_VERSION_KEY = "export_queue_version"


def _queue() -> Set[str]:
    if _QUEUE_KEY not in st.session_state:
        st.session_state[_QUEUE_KEY] = set()
    return st.session_state[_QUEUE_KEY]


def queue_size() -> int:
    return export_queue.queue_size(_queue())


def is_queued(inn: str) -> bool:
    return export_queue.is_queued(_queue(), inn)


def list_queued_inns() -> List[str]:
    return export_queue.list_queued_inns(_queue())


def remove_from_queue(inn: str) -> None:
    export_queue.remove_from_queue(_queue(), inn)


def clear_queue() -> None:
    export_queue.clear_queue(_queue())
    st.session_state[_VERSION_KEY] = st.session_state.get(_VERSION_KEY, 0) + 1


def migrate_queue_inn(old_inn: str, new_inn: str) -> None:
    export_queue.migrate_queue_inn(_queue(), old_inn, new_inn)


def toggle_export_for_inn(inn: str) -> None:
    export_queue.toggle_export_for_inn(_queue(), inn)
