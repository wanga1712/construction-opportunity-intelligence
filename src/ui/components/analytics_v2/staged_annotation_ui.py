"""Inline staged expert workflow widgets (object → mode → category)."""
from __future__ import annotations

from typing import Any, Callable

import streamlit as st

from src.services.expert_object_taxonomy import (
    OBJECT_SECTOR_LABELS_RU,
    OBJECT_SECTOR_VALUES,
    model_object_hints,
    object_subtype_options,
    object_type_options,
)
from src.services.expert_procurement_mode import (
    PROCUREMENT_MODE_LABELS_RU,
    PROCUREMENT_MODE_OPTIONS,
    model_procurement_mode_hint,
)
from src.services.source_contour import resolve_source_contour
from src.ui.components.analytics_v2.card_tabs_ai_expert_form import _sk

NEW_OBJECT_TYPE = "__NEW_OBJECT_TYPE__"


def render_source_contour_banner(source_table: str | None) -> None:
    contour = resolve_source_contour(source_table)
    st.markdown(
        f"**Источник:** 📜 {contour['law_label']} · {contour['contour_label']}"
    )
    st.caption("Факт источника (read-only). Не редактируется экспертом и не выводится моделью.")


def render_ai_suggestions_readonly(assessment: dict | None) -> None:
    hints = model_object_hints(assessment)
    mode_hint = model_procurement_mode_hint(assessment)
    bits = []
    if hints.get("object_type"):
        bits.append(f"Объект: {hints['object_type']}")
    if hints.get("sector"):
        bits.append(f"Сектор: {hints['sector']}")
    if mode_hint:
        bits.append(f"Тип закупки: {mode_hint}")
    if not bits:
        return
    st.caption("🤖 ИИ предложил (только чтение): " + " · ".join(bits))


def render_object_stage_controls(
    procurement_id: int,
    *,
    assessment: dict | None = None,
    human_type_suggestions: list[str] | None = None,
) -> None:
    """1. Object sector → type → optional subtype (+ propose new type)."""
    st.markdown("**1. Что это за объект?**")
    render_ai_suggestions_readonly(assessment)

    sector_key = _sk(procurement_id, "obj_sector")
    st.selectbox(
        "Сектор объекта",
        options=[""] + list(OBJECT_SECTOR_VALUES),
        key=sector_key,
        format_func=lambda v: "— выберите —" if not v else OBJECT_SECTOR_LABELS_RU.get(v, v),
    )
    sector = st.session_state.get(sector_key) or None
    type_options = object_type_options(sector)
    codes = [code for code, _ in type_options]
    labels = {code: label for code, label in type_options}
    # Prior human free-text values as suggestions only (not MODEL).
    for suggestion in human_type_suggestions or []:
        text = str(suggestion or "").strip()
        if text and text not in codes and text not in labels:
            codes.append(text)
            labels[text] = f"{text} (из прошлых экспертных)"

    type_key = _sk(procurement_id, "obj_type")
    options = [""] + codes + ([NEW_OBJECT_TYPE] if sector and sector != "UNCERTAIN" else [])
    st.selectbox(
        "Тип объекта",
        options=options,
        key=type_key,
        format_func=lambda v: (
            "— выберите —"
            if not v
            else ("+ Предложить новый тип объекта" if v == NEW_OBJECT_TYPE else labels.get(v, v))
        ),
        disabled=not sector,
    )
    chosen_type = st.session_state.get(type_key)
    if chosen_type == NEW_OBJECT_TYPE:
        st.text_input(
            "Новый тип объекта (предложение, не канон)",
            key=_sk(procurement_id, "obj_type_proposal"),
            help="Сохранится как taxonomy proposal, не как канонический словарь.",
        )

    subtype_opts = object_subtype_options(
        None if chosen_type in (None, "", NEW_OBJECT_TYPE) else chosen_type
    )
    subtype_key = _sk(procurement_id, "obj_subtype")
    if subtype_opts:
        sub_codes = [""] + [c for c, _ in subtype_opts]
        sub_labels = {c: lab for c, lab in subtype_opts}
        st.selectbox(
            "Подтип (необязательно)",
            options=sub_codes,
            key=subtype_key,
            format_func=lambda v: "— нет —" if not v else sub_labels.get(v, v),
        )
    elif subtype_key not in st.session_state:
        st.session_state[subtype_key] = ""


def render_procurement_mode_controls(
    procurement_id: int,
    *,
    assessment: dict | None = None,
) -> None:
    st.markdown("**2. Что закупают?**")
    hint = model_procurement_mode_hint(assessment)
    if hint:
        st.caption(f"🤖 ИИ предложил тип закупки: {PROCUREMENT_MODE_LABELS_RU.get(hint, hint)} (только чтение)")
    mode_key = _sk(procurement_id, "proc_mode")
    current = st.session_state.get(mode_key)
    if current not in PROCUREMENT_MODE_OPTIONS:
        st.session_state[mode_key] = PROCUREMENT_MODE_OPTIONS[0] if current else ""
    options = [""] + list(PROCUREMENT_MODE_OPTIONS)
    st.radio(
        "Тип закупки",
        options=options,
        key=mode_key,
        format_func=lambda v: "— выберите —" if not v else PROCUREMENT_MODE_LABELS_RU.get(v, v),
        horizontal=True,
        label_visibility="collapsed",
    )


def pending_object_type_proposal(procurement_id: int) -> list[dict]:
    """Build taxonomy proposal when operator chose + new object type."""
    if st.session_state.get(_sk(procurement_id, "obj_type")) != NEW_OBJECT_TYPE:
        return []
    name = str(st.session_state.get(_sk(procurement_id, "obj_type_proposal")) or "").strip()
    sector = st.session_state.get(_sk(procurement_id, "obj_sector"))
    if not name:
        return []
    return [
        {
            "proposal_type": "OBJECT_TYPE",
            "proposed_name": name,
            "proposed_parent_category": sector,
            "comment": "STAGED_OBJECT_PROPOSAL",
        }
    ]


def resolved_object_type(procurement_id: int) -> str | None:
    """Canonical selected type, or proposed free text when proposing new."""
    value = st.session_state.get(_sk(procurement_id, "obj_type"))
    if not value:
        return None
    if value == NEW_OBJECT_TYPE:
        proposed = str(st.session_state.get(_sk(procurement_id, "obj_type_proposal")) or "").strip()
        return proposed or None
    return str(value)


def read_staged_draft(procurement_id: int) -> dict[str, Any]:
    return {
        "object_sector": st.session_state.get(_sk(procurement_id, "obj_sector")) or None,
        "object_type": resolved_object_type(procurement_id),
        "object_subtype": st.session_state.get(_sk(procurement_id, "obj_subtype")) or None,
        "procurement_mode": st.session_state.get(_sk(procurement_id, "proc_mode")) or None,
        "taxonomy_proposals": pending_object_type_proposal(procurement_id),
    }


def init_staged_draft_from_payload(procurement_id: int, payload: dict | None) -> None:
    """Seed session keys once from existing annotation payload."""
    flag = _sk(procurement_id, "staged_init")
    if st.session_state.get(flag):
        return
    p = payload or {}
    if _sk(procurement_id, "obj_sector") not in st.session_state:
        st.session_state[_sk(procurement_id, "obj_sector")] = p.get("expert_object_sector") or ""
    if _sk(procurement_id, "obj_type") not in st.session_state:
        st.session_state[_sk(procurement_id, "obj_type")] = p.get("expert_object_type") or ""
    if _sk(procurement_id, "obj_subtype") not in st.session_state:
        st.session_state[_sk(procurement_id, "obj_subtype")] = p.get("expert_object_subtype") or ""
    if _sk(procurement_id, "proc_mode") not in st.session_state:
        st.session_state[_sk(procurement_id, "proc_mode")] = p.get("expert_procurement_mode") or ""
    st.session_state[flag] = True


def validate_staged_minimum(draft: dict[str, Any]) -> list[str]:
    missing = []
    if not draft.get("object_sector") or not draft.get("object_type"):
        missing.append("объект (сектор и тип)")
    if not draft.get("procurement_mode"):
        missing.append("тип закупки")
    return missing
