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

def is_model_hypothesis_opp(opp: dict) -> bool:
    """
    UI-level provenance guard:
    object_mode_routing contextual priors must NOT be displayed as "model result".
    """
    rc = opp.get("reason_codes") or []
    return "object_mode_contextual_prior" not in rc


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
        st.markdown("##### 🤖 Модель (read-only)")

        if ai_status in ("UNASSESSED", "INCOMPLETE", "FAILED"):
            _level = "warning" if ai_status == "UNASSESSED" else "error"
            if _level == "warning":
                st.warning(f"{icon} **{label}**")
            else:
                st.error(f"{icon} **{label}**")
            st.caption("Экспертную разметку можно добавить даже без AI-оценки.")
            return

        # ASSESSED — show MODEL fields only (no business medal/score)
        nr: dict = (assessment or {}).get("normalized_result", {})
        proc_form = nr.get("procurement_form") or "—"
        confidence = (assessment or {}).get("confidence")
        model_ver = (assessment or {}).get("model_version") or "—"

        opps_all = nr.get("category_opportunities") or []
        opps_model = [o for o in opps_all if is_model_hypothesis_opp(o)]

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Форма закупки (из модели):** `{proc_form}`")
            conf_str = f"{confidence:.0%}" if confidence is not None else "—"
            st.markdown(f"**Уверенность модели:** `{conf_str}`")
        with col2:
            st.markdown(f"**Модель:** `{model_ver}`")

        if opps_model:
            st.markdown("**Гипотезы модели:**")
            for i, opp in enumerate(opps_model, 1):
                cat = opp.get("category_code", "—")
                sub = opp.get("subcategory_code") or ""
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
            st.caption(
                "Модель не вернула коммерческие гипотезы категорий "
                "(или они скрыты как contextual priors)."
            )
