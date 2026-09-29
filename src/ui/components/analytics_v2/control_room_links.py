"""Click-through wiring for the control room (URL params -> workset scope).

The control-room tables link with ``?cr_cat=<category_code>`` and
``?cr_open=<crm_id>``. Both resolve against the SAME canonical authority the
category matrix uses (Second Pass ``category_evaluations`` with First Pass
``crm_procurement_category_opportunities`` fallback) -- never against the
legacy ``crm_procurements.crm_category`` column, whose code space does not
match ``crm_product_categories`` (it is NULL for the whole active workset).

A click writes the resolved scope into session state, switches the analytics
stage to "Идут торги" and re-runs. Nothing is written to the database.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Sequence

import streamlit as st

from src.services.main_dashboard_types import MEDALS

logger = logging.getLogger(__name__)

STAGE_KEY = "analytics_v2_active_stage"
TORGI_STAGE = "Идут торги"
SCOPE_IDS_KEY = "_cr_scope_ids"
SCOPE_LABEL_KEY = "_cr_scope_label"
FOCUS_TORGI_KEY = "selected_torgi_id"

__all__ = [
    "apply_control_room_links",
    "clear_control_room_scope",
    "SCOPE_IDS_KEY",
    "SCOPE_LABEL_KEY",
    "FOCUS_TORGI_KEY",
    "TORGI_STAGE",
    "STAGE_KEY",
]


def _first(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value in (None, ""):
        return None
    return str(value)


def _scope_for_category(code: str) -> tuple[List[int], str]:
    """Procurement ids of one canonical category, from the matrix authority."""
    from src.services import main_dashboard_queries as queries

    ids = sorted(
        {
            int(pid)
            for pid, cat, medal, _src in queries.load_category_medals()
            if cat == code and medal in MEDALS
        }
    )
    name = dict(queries.load_category_registry()).get(code, code)
    return ids, f"категория {name}"


def clear_control_room_scope() -> None:
    """Drop the dashboard-imposed workset scope."""
    for key in (SCOPE_IDS_KEY, SCOPE_LABEL_KEY, FOCUS_TORGI_KEY):
        st.session_state.pop(key, None)


def apply_control_room_links() -> bool:
    """Consume ``?cr_cat`` / ``?cr_open``. True means a rerun was requested."""
    try:
        params = st.query_params
    except Exception:  # noqa: BLE001 - bare/CLI runs have no query params
        return False

    category = _first(params.get("cr_cat"))
    open_ref = _first(params.get("cr_open"))
    if not category and not open_ref:
        return False

    ids: Sequence[int] = []
    label = ""
    focus: Optional[int] = None
    try:
        if category:
            ids, label = _scope_for_category(category)
        elif open_ref and open_ref.isdigit():
            focus = int(open_ref)
            ids, label = [focus], f"закупка CRM #{focus}"
    except Exception as exc:  # noqa: BLE001 - never break the page
        logger.warning("control room link failed: %s", exc)
        ids, label, focus = [], "", None
    finally:
        try:
            st.query_params.clear()
        except Exception:  # noqa: BLE001
            pass

    st.session_state[STAGE_KEY] = TORGI_STAGE
    if ids:
        st.session_state[SCOPE_IDS_KEY] = list(ids)
        st.session_state[SCOPE_LABEL_KEY] = label
        if focus is not None:
            st.session_state[FOCUS_TORGI_KEY] = focus
    st.rerun()
    return True