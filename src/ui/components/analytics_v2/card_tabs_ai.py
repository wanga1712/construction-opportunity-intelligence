"""AI / КАТЕГОРИИ tab — expert annotation orchestrator.

Replaces the legacy category-override UI with the expert annotation workflow.

Entry point:
    render_ai_tab(crm_db, procurement_id, ...) -> None

Navigation callback:
    When the user clicks "SAVE AND NEXT", this module sets
    st.session_state["annotation_go_next"] = True so the calling feed
    can advance to the next card.

Invariants:
    - MODEL RAW (procurement_ai_assessments) is never mutated.
    - crm_procurement_category_opportunities is not touched.
    - crm_manual_category_overrides is not used in this workflow.
    - Expert annotation NEVER creates confirmed_base_medal or document evidence.
"""
from __future__ import annotations

import streamlit as st
from typing import Any

from src.services.expert_annotation_service import (
    load_model_assessment_for_annotation,
    load_expert_annotation,
    save_expert_annotation,
    write_audit_row,
    save_taxonomy_proposal,
    load_categories_for_selector,
    collect_expert_object_types,
    collect_expert_work_stages,
    collect_expert_object_subtypes,
)
from src.ui.components.analytics_v2.card_tabs_ai_readonly import (
    render_model_readonly_block,
)
from src.ui.components.analytics_v2.card_tabs_ai_expert_form import (
    render_correct_fast_path,
    render_expert_full_form,
    _sk,
)

_CREATED_BY_FALLBACK = "SuperUser"  # UI boundary fallback only


def _get_created_by() -> str:
    """Return current user identity from session, or fallback.

    Auth is not implemented in this CRM build; fallback is acceptable
    at the UI boundary. Storage/service never hardcodes this value.
    """
    return st.session_state.get("user_name") or _CREATED_BY_FALLBACK


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point — called from card_compact.py
# ─────────────────────────────────────────────────────────────────────────────

def render_ai_tab(
    crm_db: Any,
    procurement_id: int,
    # Legacy positional args kept for backward-compat with card_compact.py:
    proposed_route: str = "—",
    proposed_obj_type: str = "—",
    proposed_proc_type: str = "—",
    ai_reasons: str = "—",
    eff_opps: list | None = None,
    ai_status: str = "UNASSESSED",
) -> None:
    """Render MODEL read-only block + expert annotation form."""
    st.markdown("### 🤖 Модель / Категории")

    # ── Load data ──────────────────────────────────────────────────────────
    assessment         = _load_assessment_safe(crm_db, procurement_id)
    existing_annotation = _load_annotation_safe(crm_db, procurement_id)
    categories         = _load_categories_safe(crm_db)
    expert_obj_types   = _load_expert_obj_types_safe(crm_db)
    expert_stages      = _load_expert_stages_safe(crm_db)
    expert_obj_subtypes = _load_expert_subtypes_safe(crm_db)
    created_by         = _get_created_by()

    # ── MODEL read-only block ──────────────────────────────────────────────
    render_model_readonly_block(assessment, ai_status)

    # Show saved annotation banner if exists
    if existing_annotation:
        p = existing_annotation["payload"]
        verdict  = p.get("expert_verdict", "—")
        ann_ver  = existing_annotation.get("annotation_version", 1)
        ann_by   = existing_annotation.get("created_by", "—")
        _VERDICT_EMOJI = {"CORRECT": "✅", "PARTIALLY_CORRECT": "⚠️", "WRONG": "❌"}
        st.info(
            f"{_VERDICT_EMOJI.get(verdict, '📝')} **Разметка v{ann_ver}** · "
            f"вердикт: `{verdict}` · автор: {ann_by}"
        )

    # ── Expert verdict radio ───────────────────────────────────────────────
    st.markdown("---")
    st.markdown("##### Оценка эксперта")
    verdict_opts   = ["CORRECT", "PARTIALLY_CORRECT", "WRONG"]
    verdict_labels = ["✅ ИИ определил правильно",
                      "⚠️ Частично правильно",
                      "❌ ИИ ошибся"]
    prev_verdict = (existing_annotation or {}).get("payload", {}).get(
        "expert_verdict", st.session_state.get(_sk(procurement_id, "verdict"), "CORRECT")
    )
    v_idx = verdict_opts.index(prev_verdict) if prev_verdict in verdict_opts else 0
    sel_v_label = st.radio(
        "Вердикт:",
        options=verdict_labels,
        index=v_idx,
        key=_sk(procurement_id, "verdict_radio"),
        horizontal=True,
    )
    selected_verdict = verdict_opts[verdict_labels.index(sel_v_label)]
    # Sync to session state so expert form picks it up
    st.session_state[_sk(procurement_id, "verdict")] = selected_verdict

    # ── Render appropriate form ────────────────────────────────────────────
    payload: dict | None = None

    if selected_verdict == "CORRECT":
        payload = render_correct_fast_path(
            procurement_id, assessment, existing_annotation, created_by
        )
    else:
        payload = render_expert_full_form(
            procurement_id=procurement_id,
            expert_verdict=selected_verdict,
            assessment=assessment,
            existing_annotation=existing_annotation,
            categories=categories,
            expert_object_types=expert_obj_types,
            expert_work_stages=expert_stages,
            expert_object_subtypes=expert_obj_subtypes,
            created_by=created_by,
        )

    # ── Handle save ────────────────────────────────────────────────────────
    if payload is not None:
        save_and_next = payload.pop("_save_and_next", False)
        _handle_save(
            procurement_id=procurement_id,
            payload=payload,
            assessment=assessment,
            created_by=created_by,
            crm_db=crm_db,
            save_and_next=save_and_next,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Save handler
# ─────────────────────────────────────────────────────────────────────────────

def _handle_save(
    procurement_id: int,
    payload: dict,
    assessment: dict | None,
    created_by: str,
    crm_db: Any,
    save_and_next: bool,
) -> None:
    """Persist annotation and write audit row.  Handles errors gracefully."""
    try:
        new_id = save_expert_annotation(
            procurement_id=procurement_id,
            payload=payload,
            created_by=created_by,
            crm_db=crm_db,
        )
        # Write audit trail (non-blocking)
        write_audit_row(
            procurement_id=procurement_id,
            model_raw=assessment.get("normalized_result") if assessment else None,
            annotation_payload=payload,
            crm_db=crm_db,
        )
        # Save taxonomy proposals from payload
        for prop in payload.get("taxonomy_proposals", []):
            try:
                save_taxonomy_proposal(
                    procurement_id=procurement_id,
                    annotation_id=new_id,
                    proposal=prop,
                    created_by=created_by,
                    crm_db=crm_db,
                )
            except Exception as exc:
                st.warning(f"Taxonomy proposal не сохранён: {exc}")

        # Clear draft init flag so reload fetches fresh annotation
        st.session_state.pop(_sk(procurement_id, "draft_init"), None)

        st.success(f"✅ Разметка сохранена (annotation id={new_id})")

        if save_and_next:
            st.session_state["annotation_go_next"] = True
            st.session_state["annotation_go_next_from"] = procurement_id

        st.rerun()

    except Exception as exc:
        st.error(f"❌ Ошибка сохранения разметки: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Safe loaders — never crash the tab
# ─────────────────────────────────────────────────────────────────────────────

def _load_assessment_safe(crm_db: Any, procurement_id: int) -> dict | None:
    try:
        return load_model_assessment_for_annotation(procurement_id, crm_db)
    except Exception as exc:
        st.warning(f"Не удалось загрузить AI-оценку: {exc}")
        return None


def _load_annotation_safe(crm_db: Any, procurement_id: int) -> dict | None:
    try:
        return load_expert_annotation(procurement_id, crm_db)
    except Exception as exc:
        st.warning(f"Не удалось загрузить экспертную разметку: {exc}")
        return None


def _cached_list(key: str, loader) -> list:
    cached = st.session_state.get(key)
    if cached is not None:
        return cached
    rows = loader()
    st.session_state[key] = rows
    return rows


def _load_categories_safe(crm_db: Any) -> list[dict]:
    try:
        return _cached_list(
            "_expert_taxonomy_categories",
            lambda: load_categories_for_selector(crm_db),
        )
    except Exception:
        return []


def _load_expert_obj_types_safe(crm_db: Any) -> list[str]:
    try:
        return _cached_list(
            "_expert_obj_types",
            lambda: collect_expert_object_types(crm_db),
        )
    except Exception:
        return []


def _load_expert_stages_safe(crm_db: Any) -> list[str]:
    try:
        return _cached_list(
            "_expert_work_stages",
            lambda: collect_expert_work_stages(crm_db),
        )
    except Exception:
        return []


def _load_expert_subtypes_safe(crm_db: Any) -> list[str]:
    try:
        return _cached_list(
            "_expert_obj_subtypes",
            lambda: collect_expert_object_subtypes(crm_db),
        )
    except Exception:
        return []
