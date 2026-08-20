"""Read-only MODEL / BUSINESS blocks for the AI annotation tab.

Phase 6B: MODEL authority is validated_model_result via inference_run_id only.
normalized_result is compatibility / business-enriched — never proven model.
"""
from __future__ import annotations

import streamlit as st

from src.services.commercial_routing_v3.field_provenance import ui_label
from src.services.commercial_routing_v3.model_ui_projection import (
    business_view_from_assessment,
    model_view_from_assessment,
)

_AI_STATE_LABELS = {
    "UNASSESSED": ("🔘", "AI-классификация ещё не выполнена"),
    "INCOMPLETE":  ("⚠️", "AI-оценка неполная / результат не сохранён"),
    "FAILED":      ("❌", "Ошибка выполнения AI-оценки"),
    "ASSESSED":    ("✅", "AI-оценка выполнена"),
}

_TRACK_LABELS = {
    "EMBEDDED_MATERIAL":   "Встраиваемый материал",
    "DIRECT_SUPPLY":       "Прямая поставка",
    "DESIGN_REQUIREMENT":  "Требование проекта",
    "DESIGN_INFLUENCE":    "Влияние на проект",
    "NO_COMMERCIAL_ENTRY": "Нет коммерческого входа",
    "UNKNOWN":             "Неизвестно",
}


def is_model_hypothesis_opp(opp: dict) -> bool:
    """Legacy guard: contextual priors must never display as model result."""
    rc = opp.get("reason_codes") or []
    if "object_mode_contextual_prior" in rc:
        return False
    if opp.get("provenance") in ("CONTEXT_PRIOR", "BUSINESS_RULE"):
        return False
    return True


def render_model_readonly_block(
    assessment: dict | None,
    ai_status: str = "UNASSESSED",
) -> None:
    """Render the MODEL section — read-only, no business rule fields."""
    icon, label = _AI_STATE_LABELS.get(ai_status, ("🔘", ai_status))

    with st.container(border=True):
        st.markdown("##### 🤖 Модель (read-only)")

        if ai_status in ("UNASSESSED", "INCOMPLETE", "FAILED"):
            _level = "warning" if ai_status == "UNASSESSED" else "error"
            if _level == "warning":
                st.warning(f"{icon} **{label}**")
            else:
                st.error(f"{icon} **{label}**")
            st.caption("Экспертную разметку можно добавить даже без AI-оценки.")
            return

        view = model_view_from_assessment(assessment)
        if view.get("provenance") == "UNKNOWN_LEGACY":
            st.info(view.get("label") or "Старая оценка — исходный ответ модели не сохранён")
            st.caption(
                "MODEL SOURCE: UNKNOWN_LEGACY — `inference_run_id` отсутствует. "
                "Не интерпретируйте compatibility `normalized_result` как доказанный ответ модели."
            )
            return

        st.caption(f"Источник: `{ui_label('MODEL_VALIDATED')}` · inference_run_id=`{(assessment or {}).get('inference_run_id')}`")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**object_type:** `{view.get('object_type') or '—'}`")
            st.markdown(f"**object_subtype:** `{view.get('object_subtype') or '—'}`")
            st.markdown(f"**work_stage:** `{view.get('work_stage') or '—'}`")
        with col2:
            st.markdown(f"**procurement_form:** `{view.get('procurement_form') or '—'}`")
            overall = view.get("overall_confidence")
            if overall is None:
                conf_str = "—"
            else:
                conf_str = f"{float(overall):.0%}"
            st.markdown(
                f"**Уверенность (агрегат):** `{conf_str}`  \n"
                f"<small>{ui_label(view.get('overall_confidence_provenance'))}</small>",
                unsafe_allow_html=True,
            )
            st.markdown(f"**Модель:** `{(assessment or {}).get('model_version') or '—'}`")

        hyps = view.get("hypotheses") or []
        if hyps:
            st.markdown("**Гипотезы модели:**")
            for i, opp in enumerate(hyps, 1):
                cat = opp.get("category") or "—"
                sub = opp.get("subcategory") or ""
                trk = _TRACK_LABELS.get(
                    opp.get("opportunity_track", ""),
                    opp.get("opportunity_track", "—"),
                )
                opp_conf = opp.get("confidence")
                opp_conf_str = (
                    f"{float(opp_conf) * 100:.0f}%" if opp_conf is not None else "—"
                )
                sub_s = f" / {sub}" if sub else ""
                st.markdown(
                    f"{i}. **{cat}**{sub_s} &nbsp; `{trk}` &nbsp; "
                    f"confidence `{opp_conf_str}`",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("Модель не вернула коммерческие гипотезы категорий.")


def render_business_readonly_block(assessment: dict | None) -> None:
    """Render BUSINESS section — explicit rule provenance, never 'AI result'."""
    biz = business_view_from_assessment(assessment)
    with st.container(border=True):
        st.markdown("##### ⚙️ Бизнес-оценка (правила CRM)")
        st.caption(ui_label("BUSINESS_RULE"))
        st.markdown(f"**route_profile:** `{biz.get('route_profile') or '—'}`")
        st.markdown(f"**business_scope_status:** `{biz.get('business_scope_status') or '—'}`")
        base = biz.get("business_candidate_medal") or "—"
        eff = biz.get("effective_medal")
        score = biz.get("business_candidate_score")
        score_s = f"{float(score):.1f}" if score is not None else "—"
        st.markdown(f"**Базовая бизнес-медаль:** `{base}` · score `{score_s}`")
        if eff is not None and str(eff) != str(base):
            st.markdown(f"**Текущая медаль:** `{eff}`")
            st.caption("Причина расхождения: timing/window / effective assessment")
        priors = biz.get("contextual_prior_hypotheses") or []
        if priors:
            st.markdown("**Контекстные prior-гипотезы (не модель):**")
            for i, h in enumerate(priors[:5], 1):
                st.markdown(
                    f"{i}. `{h.get('category_code') or h.get('category') or '—'}` "
                    f"· provenance=`CONTEXT_PRIOR`"
                )
