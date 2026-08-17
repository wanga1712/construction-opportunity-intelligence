"""Read-only MODEL RAW block for the AI annotation tab.

Single public function:
    render_model_readonly_block(assessment: dict | None, ai_status: str) -> None

Renders what the model decided — never editable here.
"""
from __future__ import annotations

import streamlit as st

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

_MEDAL_EMOJI = {"GOLD": "🥇", "SILVER": "🥈", "BRONZE": "🥉", "WOOD": "🪵"}


def render_model_readonly_block(
    assessment: dict | None,
    ai_status: str = "UNASSESSED",
) -> None:
    """Render the MODEL RAW section — read-only, no controls.

    ``assessment`` is the result of
    ``expert_annotation_service.load_model_assessment_for_annotation()``.
    """
    icon, label = _AI_STATE_LABELS.get(ai_status, ("🔘", ai_status))

    with st.container(border=True):
        st.markdown("##### 🤖 Результат модели (read-only)")

        if ai_status in ("UNASSESSED", "INCOMPLETE", "FAILED"):
            _level = "warning" if ai_status == "UNASSESSED" else "error"
            if _level == "warning":
                st.warning(f"{icon} **{label}**")
            else:
                st.error(f"{icon} **{label}**")
            st.caption("Экспертную разметку можно добавить даже без AI-оценки.")
            return

        # ASSESSED — show normalised result fields
        nr: dict = (assessment or {}).get("normalized_result", {})
        proc_form    = nr.get("procurement_form") or "—"
        obj_type     = nr.get("object_type") or "—"
        obj_subtype  = nr.get("object_subtype") or "—"
        proj_stage   = nr.get("project_stage") or "—"
        candidate_lv = nr.get("candidate_level") or "—"
        candidate_sc = nr.get("candidate_score")
        confidence   = (assessment or {}).get("confidence")
        model_ver    = (assessment or {}).get("model_version") or "—"
        reasons      = (assessment or {}).get("reasons") or "—"
        opps         = nr.get("category_opportunities") or []
        timing       = nr.get("timing") or nr.get("timing_context") or {}
        remaining_days = (
            timing.get("remaining_working_days")
            if isinstance(timing, dict) else None
        )
        required_days = (
            timing.get("required_working_days")
            if isinstance(timing, dict) else None
        )
        window_status = (
            timing.get("window_status") or timing.get("commercial_window_status")
            if isinstance(timing, dict) else None
        )
        remaining_days = nr.get("remaining_working_days", remaining_days)
        required_days = nr.get("required_working_days", required_days)
        window_status = nr.get("commercial_window_status", window_status)

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Форма закупки:** `{proc_form}`")
            st.markdown(f"**Объект:** `{obj_type}`")
            st.markdown(f"**Подтип:** `{obj_subtype}`")
            st.markdown(f"**Стадия:** `{proj_stage}`")
        with col2:
            medal_em = _MEDAL_EMOJI.get(candidate_lv, "")
            score_str = f" · score {candidate_sc:.0f}" if candidate_sc is not None else ""
            st.markdown(f"**Медаль ИИ:** {medal_em} `{candidate_lv}`{score_str}")
            conf_str = f"{confidence:.0%}" if confidence is not None else "—"
            st.markdown(f"**Уверенность:** `{conf_str}`")
            st.markdown(f"**Модель:** `{model_ver}`")

        if any(value is not None for value in (remaining_days, required_days, window_status)):
            st.caption(
                "Детерминированный timing (read-only): "
                f"осталось рабочих дней = `{remaining_days if remaining_days is not None else '—'}` · "
                f"требуется = `{required_days if required_days is not None else '—'}` · "
                f"окно = `{window_status or '—'}`"
            )

        if reasons and reasons != "—":
            with st.expander("Обоснование модели", expanded=False):
                st.caption(reasons)

        if opps:
            st.markdown("**Гипотезы модели:**")
            for i, opp in enumerate(opps, 1):
                cat  = opp.get("category_code", "—")
                sub  = opp.get("subcategory_code") or ""
                trk  = _TRACK_LABELS.get(opp.get("opportunity_track", ""), opp.get("opportunity_track", "—"))
                lvl  = _MEDAL_EMOJI.get(opp.get("candidate_level", ""), "") + " " + (opp.get("candidate_level") or "—")
                sc   = opp.get("candidate_score")
                sc_s = f" · {sc:.0f}" if sc is not None else ""
                sub_s = f" / {sub}" if sub else ""
                st.markdown(
                    f"{i}. **{cat}**{sub_s} &nbsp; `{trk}`"
                    f" &nbsp; {lvl}{sc_s}",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("Гипотезы категорий не найдены.")
