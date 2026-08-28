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


def render_learning_loop_results(crm_db: Any, procurement_id: int) -> None:
    """Render the Hunter-Auditor learning loop results in the card."""
    # Fetch latest trace
    traces = crm_db.execute_query(
        """
        SELECT hunter_run_id, auditor_run_id, consensus_state
        FROM crm_v3_autonomous_analysis_traces
        WHERE procurement_id = %s
        ORDER BY id DESC LIMIT 1
        """,
        (procurement_id,),
    )
    if not traces:
        return
    trace = traces[0]
    hunter_run_id = trace.get("hunter_run_id")
    auditor_run_id = trace.get("auditor_run_id")
    consensus = trace.get("consensus_state")

    # Fetch hunter result
    hunter_result = {}
    if hunter_run_id:
        hr = crm_db.execute_query(
            "SELECT validated_model_result FROM crm_v3_model_inference_runs WHERE id = %s",
            (hunter_run_id,),
        )
        if hr:
            hunter_result = hr[0].get("validated_model_result") or {}

    # Fetch auditor result
    auditor_result = {}
    if auditor_run_id:
        ar = crm_db.execute_query(
            "SELECT validated_model_result FROM crm_v3_model_inference_runs WHERE id = %s",
            (auditor_run_id,),
        )
        if ar:
            auditor_result = ar[0].get("validated_model_result") or {}

    # Fetch observations
    obs = crm_db.execute_query(
        """
        SELECT document_title, source_document_url, usefulness_label, download_status, parse_status
        FROM crm_v3_document_observations
        WHERE procurement_id = %s
        ORDER BY id ASC
        """,
        (procurement_id,),
    ) or []

    # Fetch latest trace to get the hunter_run_id for latest-run authority
    latest_trace = crm_db.execute_query_one(
        """
        SELECT hunter_run_id
        FROM crm_v3_autonomous_analysis_traces
        WHERE procurement_id = %s
        ORDER BY id DESC LIMIT 1
        """,
        (procurement_id,),
    )
    hunter_run_id = latest_trace["hunter_run_id"] if latest_trace else None

    # Fetch product findings matching latest run_id
    products = []
    if hunter_run_id is not None:
        products = crm_db.execute_query(
            """
            SELECT category_code, product_type, product_name_normalized, brand, model,
                   quantity, unit, raw_description, evidence_text, document_name,
                   page, sheet, row_num, position_number
            FROM crm_v3_product_findings
            WHERE procurement_id = %s AND model_run_id = %s AND extractor_role = 'HUNTER'
            ORDER BY id ASC
            """,
            (procurement_id, hunter_run_id),
        ) or []

    with st.container(border=True):
        st.markdown("#### 🔍 Найдено в закупке (Умный поиск)")
        
        # Object sector & type
        obj_sector = hunter_result.get("object_sector") or "—"
        obj_type = hunter_result.get("object_type") or "—"
        obj_subtype = hunter_result.get("object_subtype") or "—"
        st.markdown(f"**Объект:** `{obj_sector}` &rarr; `{obj_type}` &rarr; `{obj_subtype}`")
        
        # Procurement mode
        mode = hunter_result.get("procurement_mode") or "—"
        st.markdown(f"**Режим закупки:** `{mode}`")
        
        # Categories
        cats = hunter_result.get("categories") or []
        st.markdown(f"**Наши категории:** {', '.join(f'`{c}`' for c in cats) if cats else '—'}")
        
        # Document coverage
        total_docs = len(obs)
        failed_docs = sum(1 for o in obs if o.get("usefulness_label") in ("DOWNLOAD_FAILED", "PARSE_FAILED"))
        if total_docs > 0:
            searched_docs = total_docs - failed_docs
            st.markdown(f"**Документы исследованы:** `{searched_docs} / {total_docs}`")
            if failed_docs > 0:
                st.markdown(f"⚠️ `{failed_docs}` документа не удалось прочитать  \n*Вывод неполный*")
        else:
            st.markdown("**Документы исследованы:** `0 / 0` (нет документов)")

        # Products
        st.markdown("**Найденные товары / материалы:**")
        if products:
            for idx, p in enumerate(products, 1):
                p_name = p.get("product_name_normalized") or p.get("product_type") or "Товар"
                brand = f" (Бренд: {p['brand']})" if p.get("brand") else ""
                model = f" (Модель: {p['model']})" if p.get("model") else ""
                qty = f" &nbsp; **{p['quantity']}** {p['unit']}" if p.get("quantity") is not None else ""
                
                doc_name = p.get("document_name") or "Документ"
                # Find matching observation to get URL
                doc_url = next((o.get("source_document_url") for o in obs if o.get("document_title") == doc_name), None)
                doc_link = f"[{doc_name}]({doc_url})" if doc_url else doc_name
                
                loc_parts = []
                if p.get("page"): loc_parts.append(f"стр. {p['page']}")
                if p.get("sheet"): loc_parts.append(f"лист \"{p['sheet']}\"")
                if p.get("row_num"): loc_parts.append(f"строка {p['row_num']}")
                if p.get("position_number"): loc_parts.append(f"поз. {p['position_number']}")
                loc_str = ", ".join(loc_parts) or "—"
                
                st.markdown(
                    f"{idx}. **{p_name}**{brand}{model}{qty}  \n"
                    f"&nbsp; &nbsp; Категория: `{p.get('category_code')}`  \n"
                    f"&nbsp; &nbsp; Найдено в: {doc_link} ({loc_str})  \n"
                    f"&nbsp; &nbsp; Цитата: *\"{p.get('evidence_text') or '—'}\"*",
                    unsafe_allow_html=True
                )
        else:
            if total_docs > 0 and failed_docs == 0:
                st.markdown(f"*По нашим товарным категориям ничего не найдено после полного исследования {total_docs}/{total_docs} документов*")
            else:
                st.markdown("*Товары / материалы не найдены*")

        st.markdown("---")
        st.markdown(f"**Вердикт Hunter:** `{hunter_result.get('medal_hypothesis') or '—'}` (уверенность {hunter_result.get('confidence', 0.0):.0%})")
        st.markdown(f"**Вердикт Auditor:** `{auditor_result.get('medal', {}).get('verdict') or '—'}` (consensus: `{consensus}`)")

