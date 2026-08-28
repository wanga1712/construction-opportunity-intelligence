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

import logging
import streamlit as st
from typing import Any

logger = logging.getLogger("card_tabs_ai")

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
    render_business_readonly_block,
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
    assessment = _load_assessment_safe(crm_db, procurement_id)
    existing_annotation = _load_annotation_safe(crm_db, procurement_id)

    render_model_readonly_block(assessment, ai_status)
    render_learning_loop_results(crm_db, procurement_id)
    # ── BUSINESS read-only block (rules — never labeled as model) ─────────
    if ai_status == "ASSESSED":
        render_business_readonly_block(assessment)

    if existing_annotation:
        p = existing_annotation["payload"]
        verdict = p.get("expert_verdict", "—")
        ann_ver = existing_annotation.get("annotation_version", 1)
        ann_by = existing_annotation.get("created_by", "—")
        _VERDICT_EMOJI = {"CORRECT": "✅", "PARTIALLY_CORRECT": "⚠️", "WRONG": "❌", "PARTIAL_REVIEW": "📝"}
        st.info(
            f"{_VERDICT_EMOJI.get(verdict, '📝')} **Разметка v{ann_ver}** · "
            f"вердикт: `{verdict}` · автор: {ann_by}"
        )

    st.markdown("---")
    st.warning(
        "**Экспертная разметка выполняется только в sidebar → 🏷️ РАЗМЕТКА.**  "
        "Вкладка «Идут торги» показывает publication-visible подмножество (~20), "
        "не полную очередь open+assessed (~66)."
    )
    if st.button(
        "🏷️ Открыть эту карточку в РАЗМЕТКА",
        key=f"goto_annotation_wb_{procurement_id}",
        type="primary",
    ):
        st.session_state["nav_page"] = "expert_annotation"
        st.session_state["annotation_wb_queue"] = procurement_id
        st.session_state.pop("annotation_wb_filters", None)
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Save handler (used by tests; primary UI is annotation_workbench_page)
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
        # Record feedback rewards
        try:
            from src.services.commercial_routing_v3.reward_ledger_service import RewardLedgerService
            rl_service = RewardLedgerService(crm_db)
            rl_service.record_feedback_rewards(procurement_id, payload)
        except Exception as exc:
            logger.warning(f"Failed to record feedback rewards: {exc}")

        # Write audit trail (non-blocking)
        write_audit_row(
            procurement_id=procurement_id,
            model_raw=(
                (assessment.get("validated_model_result") if assessment else None)
                or (assessment.get("normalized_result") if assessment else None)
            ),
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
