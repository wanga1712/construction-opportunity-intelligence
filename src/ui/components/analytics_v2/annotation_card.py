"""Fast expert annotation card for the РАЗМЕТКА workbench."""
from __future__ import annotations

import json
import streamlit as st
from typing import Any

from src.domain.commercial_routing_v3 import OpportunityTrack
from src.services.commercial_routing_v3.model_ui_projection import (
    business_view_from_assessment,
    model_view_from_assessment,
)
from src.services.expert_annotation_service import (
    load_categories_for_selector,
    collect_expert_object_types,
    collect_expert_work_stages,
    collect_expert_object_subtypes,
    load_document_findings_for_annotation,
    save_expert_annotation,
    write_audit_row,
)
from src.services.annotation_readiness import (
    COMPLETENESS_STATES,
    EVIDENCE_STATES,
    REVIEW_SCOPES,
    training_eligibility_reasons,
)
from src.services.annotation_card_provenance import load_annotation_history
from src.ui.components.analytics_v2.card_tabs_ai_expert_form import (
    _assemble_payload,
    _renumber,
    _sk,
)
from src.ui.components.analytics_v2.annotation_card_sections import (
    render_documents,
    render_history,
    render_overview,
    render_workbench_header,
)
from src.ui.components.analytics_v2.annotation_queue import GO_NEXT_FROM_KEY, GO_NEXT_KEY

_CREATED_BY_FALLBACK = "SuperUser"


def _training_evidence_quality(assessment: dict | None) -> str:
    if assessment and assessment.get("inference_run_id") and assessment.get("model_provenance") == "MODEL_VALIDATED":
        return "IMMUTABLE_MODEL_TRACE"
    return "LEGACY_NO_RAW"


def _legacy_category_rows(assessment: dict | None) -> list[dict]:
    nr = (assessment or {}).get("normalized_result") or {}
    rows = []
    for idx, opp in enumerate(nr.get("category_opportunities") or []):
        code = opp.get("category_code")
        if not code:
            continue
        rows.append({
            "category_code": code,
            "subcategory_code": opp.get("subcategory_code"),
            "opportunity_track": opp.get("opportunity_track", "EMBEDDED_MATERIAL"),
            "model_opportunity_index": idx,
            "provenance": "LEGACY_BUSINESS",
            "model_opportunity_snapshot": dict(opp),
        })
    return rows


def model_category_rows(assessment: dict | None) -> list[dict]:
    """Categories the UI may show for per-category verdict buttons."""
    view = model_view_from_assessment(assessment)
    if view.get("provenance") == "MODEL_VALIDATED":
        rows = []
        for idx, h in enumerate(view.get("hypotheses") or []):
            code = h.get("category")
            if not code:
                continue
            rows.append({
                "category_code": code,
                "subcategory_code": h.get("subcategory"),
                "opportunity_track": h.get("opportunity_track", "EMBEDDED_MATERIAL"),
                "confidence": h.get("confidence"),
                "model_opportunity_index": idx,
                "provenance": "MODEL_VALIDATED",
                "model_opportunity_snapshot": dict(h),
            })
        return rows
    return _legacy_category_rows(assessment)


def rejected_raw_categories(assessment: dict | None) -> list[dict]:
    """Validator-rejected RAW category codes (immutable trace only)."""
    if not assessment or assessment.get("model_provenance") != "MODEL_VALIDATED":
        return []
    raw = assessment.get("raw_model_json") or {}
    if not isinstance(raw, dict):
        return []
    validated = assessment.get("validated_model_result") or {}
    valid_codes = {
        h.get("category_code")
        for h in (validated.get("commercial_category_hypotheses") or [])
        if isinstance(h, dict) and h.get("category_code")
    }
    out = []
    for key in ("commercial_category_hypotheses", "commercial_category_candidates"):
        for item in raw.get(key) or []:
            if not isinstance(item, dict):
                continue
            code = item.get("category_code") or item.get("commercial_category_code")
            if not code or code in valid_codes:
                continue
            out.append({
                "raw_category_code": code,
                "validation_status": assessment.get("validation_status"),
                "validation_errors": list(assessment.get("validation_errors") or []),
            })
    return out


def _init_fast_draft(
    procurement_id: int,
    assessment: dict | None,
    existing_annotation: dict | None,
) -> None:
    sk_init = _sk(procurement_id, "fast_init")
    if st.session_state.get(sk_init):
        return
    if existing_annotation:
        p = existing_annotation.get("payload", {})
        st.session_state[_sk(procurement_id, "opps")] = list(p.get("opportunities") or [])
        st.session_state[_sk(procurement_id, "rejected")] = list(
            p.get("rejected_model_opportunities") or []
        )
        st.session_state[_sk(procurement_id, "obj_type")] = p.get("expert_object_type") or ""
        st.session_state[_sk(procurement_id, "obj_subtype")] = p.get("expert_object_subtype") or ""
        st.session_state[_sk(procurement_id, "work_stage")] = p.get("expert_work_stage") or ""
        st.session_state[_sk(procurement_id, "absence_confirmed")] = bool(
            p.get("expert_category_absence_confirmed")
        )
        st.session_state[_sk(procurement_id, "review_scope")] = p.get("annotation_review_scope") or "CATEGORY_ONLY"
        st.session_state[_sk(procurement_id, "completeness")] = p.get("annotation_completeness") or "PARTIAL"
        st.session_state[_sk(procurement_id, "evidence_state")] = p.get("evidence_state") or "SUFFICIENT"
        st.session_state[_sk(procurement_id, "document_priorities")] = {
            item.get("document_key"): item.get("priority")
            for item in (p.get("document_review_priorities") or [])
            if isinstance(item, dict) and item.get("document_key") and item.get("priority")
        }
    else:
        draft = []
        for row in model_category_rows(assessment):
            draft.append({
                "expert_rank": len(draft) + 1,
                "expert_action": "KEEP",
                "category_code": row["category_code"],
                "subcategory_code": row.get("subcategory_code"),
                "opportunity_track": row.get("opportunity_track", OpportunityTrack.EMBEDDED_MATERIAL),
                "hypothesis_reasons": [],
                "expected_document_sources": [],
                "model_opportunity_snapshot": row.get("model_opportunity_snapshot"),
                "model_opportunity_index": row.get("model_opportunity_index"),
                "comment": "",
                "expert_reviewed": False,
            })
        st.session_state[_sk(procurement_id, "opps")] = draft
        st.session_state[_sk(procurement_id, "rejected")] = []
        st.session_state[_sk(procurement_id, "obj_type")] = ""
        st.session_state[_sk(procurement_id, "obj_subtype")] = ""
        st.session_state[_sk(procurement_id, "work_stage")] = ""
        st.session_state[_sk(procurement_id, "absence_confirmed")] = False
        st.session_state[_sk(procurement_id, "review_scope")] = "CATEGORY_ONLY"
        st.session_state[_sk(procurement_id, "completeness")] = "PARTIAL"
        st.session_state[_sk(procurement_id, "evidence_state")] = "SUFFICIENT"
        st.session_state[_sk(procurement_id, "document_priorities")] = {}
    st.session_state[sk_init] = True


def _mark_category_correct(procurement_id: int, category_code: str) -> None:
    opps = st.session_state[_sk(procurement_id, "opps")]
    rejected = st.session_state[_sk(procurement_id, "rejected")]
    for rej in list(rejected):
        if rej.get("category_code") == category_code:
            rejected.remove(rej)
            rej["expert_action"] = "KEEP"
            rej["expert_reviewed"] = True
            rej["expert_rank"] = len(opps) + 1
            opps.append(rej)
            _renumber(opps)
            return
    for opp in opps:
        if opp.get("category_code") == category_code:
            opp["expert_action"] = "KEEP"
            opp["expert_reviewed"] = True
            return


def _mark_category_wrong(procurement_id: int, category_code: str) -> None:
    opps = st.session_state[_sk(procurement_id, "opps")]
    rejected = st.session_state[_sk(procurement_id, "rejected")]
    for i, opp in enumerate(list(opps)):
        if opp.get("category_code") == category_code:
            victim = opps.pop(i)
            victim["expert_action"] = "REJECT"
            victim["expert_rank"] = None
            victim["rejection_reason"] = victim.get("rejection_reason") or "WRONG_CATEGORY"
            victim["expert_reviewed"] = True
            rejected.append(victim)
            _renumber(opps)
            return


def _build_out_of_profile_payload(assessment: dict | None, created_by: str) -> dict:
    rejected = []
    for row in model_category_rows(assessment):
        rejected.append({
            "expert_action": "REJECT",
            "category_code": row["category_code"],
            "subcategory_code": row.get("subcategory_code"),
            "opportunity_track": row.get("opportunity_track", "EMBEDDED_MATERIAL"),
            "rejection_reason": "OUT_OF_PROFILE",
            "model_opportunity_snapshot": row.get("model_opportunity_snapshot"),
            "model_opportunity_index": row.get("model_opportunity_index"),
            "comment": "",
        })
    return {
        "model_assessment_id": (assessment or {}).get("id"),
        "expert_verdict": "WRONG",
        "expert_procurement_form": None,
        "expert_object_type": None,
        "expert_object_subtype": None,
        "expert_work_stage": None,
        "expert_commercial_verdict": "NO_COMMERCIAL_ENTRY",
        "expert_medal": "NCE",
        "medal_reason": "OTHER",
        "medal_comment": "",
        "error_reasons": ["OUT_OF_PROFILE"],
        "expert_comment": "",
        "expert_scope_verdict": "OUT_OF_PROFILE",
        "annotation_review_scope": "OUT_OF_PROFILE",
        "annotation_completeness": "COMPLETE",
        "evidence_state": "SUFFICIENT",
        "opportunities": [],
        "rejected_model_opportunities": rejected,
        "taxonomy_proposals": [],
        "training_evidence_quality": _training_evidence_quality(assessment),
        "created_by": created_by,
    }


def render_annotation_card(
    *,
    crm_db: Any,
    procurement_id: int,
    header: dict,
    assessment: dict | None,
    existing_annotation: dict | None,
    publication_visible: bool,
    lifecycle_label: str,
    created_by: str | None = None,
) -> None:
    """Render one fast annotation card. Handles save + SAVE+NEXT via session flags."""
    created_by = created_by or st.session_state.get("user_name") or _CREATED_BY_FALLBACK
    _init_fast_draft(procurement_id, assessment, existing_annotation)

    categories = load_categories_for_selector(crm_db)
    cat_codes = [c["code"] for c in categories]
    cat_labels = [f"{c['code']} ({c['name']})" for c in categories]
    expert_obj_types = collect_expert_object_types(crm_db)
    expert_stages = collect_expert_work_stages(crm_db)
    expert_subtypes = collect_expert_object_subtypes(crm_db)

    render_workbench_header(header, procurement_id, lifecycle_label, publication_visible)
    documents = load_document_findings_for_annotation(procurement_id, crm_db)
    history = load_annotation_history(crm_db, procurement_id, header)
    priority_state = st.session_state[_sk(procurement_id, "document_priorities")]

    overview_tab, model_tab, documents_tab, history_tab, expert_tab = st.tabs(
        ["Обзор", "Модель / Категории", "Документы", "История", "Экспертная разметка"]
    )
    with overview_tab:
        render_overview(header, assessment, existing_annotation)
    with model_tab:
        _render_ai_block(assessment)
        _render_business_block(assessment)
        _render_category_verdicts(procurement_id, assessment, categories, cat_codes, cat_labels)
    with documents_tab:
        render_documents(procurement_id, documents, priority_state)
    with history_tab:
        render_history(history)
    with expert_tab:
        _render_expert_object_stage(procurement_id, assessment, expert_obj_types, expert_subtypes, expert_stages)
        _render_ranked_expert_categories(procurement_id, cat_codes, cat_labels)
        _render_review_contract(procurement_id, crm_db)
        _render_technical_details(assessment, existing_annotation)

    b1, b2, b3 = st.columns(3)
    save = b1.button("💾 Сохранить", key=_sk(procurement_id, "wb_save"))
    save_next = b2.button(
        "💾 SAVE & NEXT →",
        key=_sk(procurement_id, "wb_save_next"),
        type="primary",
    )
    if b3.button("⛔ НЕ НАШ ПРОФИЛЬ", key=_sk(procurement_id, "wb_oop")):
        payload = _build_out_of_profile_payload(assessment, created_by)
        payload["document_review_priorities"] = _document_priority_payload(procurement_id)
        _persist(procurement_id, payload, assessment, created_by, crm_db, save_and_next=True)
        return

    if save or save_next:
        payload = _build_workbench_payload(procurement_id, assessment, created_by)
        _persist(procurement_id, payload, assessment, created_by, crm_db, save_and_next=save_next)


def _render_ai_block(assessment: dict | None) -> None:
    with st.container(border=True):
        st.markdown("##### 🤖 ИИ ПРЕДЛОЖИЛ")
        view = model_view_from_assessment(assessment)
        if view.get("provenance") == "UNKNOWN_LEGACY":
            st.warning("⚠ **ИСТОРИЧЕСКАЯ ОЦЕНКА** — RAW модели не сохранён")
            nr = (assessment or {}).get("normalized_result") or {}
            st.caption(
                f"subject: `{nr.get('subject_interpretation') or '—'}` · "
                f"form: `{nr.get('procurement_form') or '—'}` · "
                f"object: `{nr.get('object_type') or '—'}` / `{nr.get('object_subtype') or '—'}` · "
                f"stage: `{nr.get('project_stage') or nr.get('work_stage') or '—'}`"
            )
            legacy = _legacy_category_rows(assessment)
            if legacy:
                st.caption("_Legacy/business provenance — не MODEL_VALIDATED:_")
                for row in legacy:
                    st.markdown(f"- `{row['category_code']}`")
            return

        st.caption(f"MODEL_VALIDATED · inference_run_id=`{(assessment or {}).get('inference_run_id')}`")
        st.markdown(
            f"**object:** `{view.get('object_type') or '—'}` / `{view.get('object_subtype') or '—'}` · "
            f"**stage:** `{view.get('work_stage') or '—'}` · "
            f"**form:** `{view.get('procurement_form') or '—'}`"
        )
        nr = (assessment or {}).get("normalized_result") or {}
        if nr.get("subject_interpretation"):
            st.markdown(f"**subject_interpretation:** `{nr['subject_interpretation']}`")
        if nr.get("research_priority") is not None:
            st.markdown(f"**research priority:** `{nr.get('research_priority')}`")
        hyps = view.get("hypotheses") or []
        if hyps:
            for i, h in enumerate(hyps, 1):
                sub = f" / {h.get('subcategory')}" if h.get("subcategory") else ""
                st.markdown(f"{i}. **{h.get('category')}**{sub}")
        else:
            st.info("ИИ не выбрал коммерческую категорию")

        for rej in rejected_raw_categories(assessment):
            errs = ", ".join(rej.get("validation_errors") or []) or "—"
            st.error(
                f"RAW модели: `{rej.get('raw_category_code')}` · "
                f"Статус: Отклонено validator · Причина: {errs}"
            )


def _render_business_block(assessment: dict | None) -> None:
    biz = business_view_from_assessment(assessment)
    nr = (assessment or {}).get("normalized_result") or {}
    medal = biz.get("business_candidate_medal") or "—"
    score = biz.get("business_candidate_score")
    score_s = f"{float(score):.0f}" if score is not None else "—"
    st.markdown("##### ⚙️ BUSINESS RULE RESULT")
    st.markdown(
        f"**Route:** `{biz.get('route_profile') or '—'}` · "
        f"**scope:** `{biz.get('business_scope_status') or '—'}` · "
        f"**medal / score:** {medal} / {score_s}"
    )
    business_categories = nr.get("category_opportunities") or []
    if business_categories:
        st.markdown("**Текущие business-selected категории:**")
        for item in business_categories:
            st.markdown(
                f"- `{item.get('category_code') or '—'}` / "
                f"`{item.get('subcategory_code') or '—'}` · "
                f"{item.get('candidate_medal') or item.get('candidate_level') or '—'} · "
                f"score={item.get('candidate_score') if item.get('candidate_score') is not None else '—'}"
            )


def _render_category_verdicts(
    procurement_id: int,
    assessment: dict | None,
    categories: list[dict],
    cat_codes: list[str],
    cat_labels: list[str],
) -> None:
    st.markdown("---")
    st.markdown("##### 👤 ЭКСПЕРТНАЯ РАЗМЕТКА")
    st.markdown("###### Категории — быстрая разметка")
    rows = model_category_rows(assessment)
    if not rows:
        st.info("ИИ не выбрал коммерческую категорию")
        if st.button("✓ КАТЕГОРИИ ДЕЙСТВИТЕЛЬНО НЕТ", key=_sk(procurement_id, "confirm_none")):
            st.session_state[_sk(procurement_id, "absence_confirmed")] = True
            st.session_state[_sk(procurement_id, "opps")] = []
            st.rerun()
        if st.session_state.get(_sk(procurement_id, "absence_confirmed")):
            st.success("Эксперт подтвердил: коммерческих категорий нет")
    else:
        for row in rows:
            code = row["category_code"]
            c1, c2, c3 = st.columns([3, 1, 1])
            c1.markdown(f"**{code}**")
            if c2.button("✓ ВЕРНО", key=_sk(procurement_id, f"ok_{code}")):
                _mark_category_correct(procurement_id, code)
                st.rerun()
            if c3.button("✕ НЕВЕРНО", key=_sk(procurement_id, f"bad_{code}")):
                _mark_category_wrong(procurement_id, code)
                st.rerun()

    if st.button("+ ДОБАВИТЬ ПРОПУЩЕННУЮ КАТЕГОРИЮ", key=_sk(procurement_id, "add_missed")):
        st.session_state[_sk(procurement_id, "show_add_missed")] = True
    if st.session_state.get(_sk(procurement_id, "show_add_missed")) and cat_codes:
        sel = st.selectbox("Категория из реестра:", cat_labels, key=_sk(procurement_id, "missed_sel"))
        if st.button("Добавить", key=_sk(procurement_id, "missed_add_btn")):
            code = cat_codes[cat_labels.index(sel)]
            opps = st.session_state[_sk(procurement_id, "opps")]
            if not any(o.get("category_code") == code for o in opps):
                opps.append({
                    "expert_rank": len(opps) + 1,
                    "expert_action": "ADD",
                    "category_code": code,
                    "subcategory_code": None,
                    "opportunity_track": OpportunityTrack.EMBEDDED_MATERIAL,
                    "hypothesis_reasons": ["EXPERT_COMMERCIAL_KNOWLEDGE"],
                    "expected_document_sources": [],
                    "model_opportunity_snapshot": None,
                    "model_opportunity_index": None,
                    "comment": "",
                    "expert_reviewed": True,
                })
            st.session_state[_sk(procurement_id, "show_add_missed")] = False
            st.rerun()


def _render_expert_object_stage(
    procurement_id: int,
    assessment: dict | None,
    obj_types: list[str],
    subtypes: list[str],
    stages: list[str],
) -> None:
    view = model_view_from_assessment(assessment)
    nr = (assessment or {}).get("normalized_result") or {}
    st.markdown("---")
    st.markdown("##### Объект / стадия (эксперт)")
    st.caption(
        f"ИИ предложил: `{view.get('object_type') or nr.get('object_type') or '—'}` / "
        f"`{view.get('object_subtype') or nr.get('object_subtype') or '—'}` / "
        f"`{view.get('work_stage') or nr.get('project_stage') or '—'}`"
    )
    st.text_input(
        "expert_object_type",
        key=_sk(procurement_id, "obj_type"),
        help=", ".join(obj_types[:8]) if obj_types else "",
    )
    st.text_input("expert_object_subtype", key=_sk(procurement_id, "obj_subtype"))
    st.text_input("expert_work_stage", key=_sk(procurement_id, "work_stage"))


def _render_ranked_expert_categories(
    procurement_id: int,
    cat_codes: list[str],
    cat_labels: list[str],
) -> None:
    opps = st.session_state.get(_sk(procurement_id, "opps"), [])
    if not opps:
        return
    st.markdown("---")
    st.markdown("##### Экспертный rank")
    for i, opp in enumerate(opps):
        c1, c2, c3, c4 = st.columns([4, 1, 1, 1])
        c1.markdown(f"{i + 1}. **{opp.get('category_code', '—')}** [{opp.get('expert_action', 'KEEP')}]")
        if i > 0 and c2.button("↑", key=_sk(procurement_id, f"rank_up_{i}")):
            opps[i - 1], opps[i] = opps[i], opps[i - 1]
            _renumber(opps)
            st.rerun()
        if i < len(opps) - 1 and c3.button("↓", key=_sk(procurement_id, f"rank_dn_{i}")):
            opps[i], opps[i + 1] = opps[i + 1], opps[i]
            _renumber(opps)
            st.rerun()
        if c4.button("×", key=_sk(procurement_id, f"rank_del_{i}")):
            victim = opps.pop(i)
            if victim.get("model_opportunity_index") is not None:
                victim["expert_action"] = "REJECT"
                victim["expert_reviewed"] = True
                victim["expert_rank"] = None
                victim["rejection_reason"] = victim.get("rejection_reason") or "WRONG_CATEGORY"
                st.session_state[_sk(procurement_id, "rejected")].append(victim)
            _renumber(opps)
            st.rerun()


def _render_review_contract(procurement_id: int, crm_db: Any) -> None:
    st.markdown("---")
    st.markdown("##### Объём и полнота экспертной проверки")
    st.selectbox("annotation_review_scope", REVIEW_SCOPES, key=_sk(procurement_id, "review_scope"))
    st.selectbox("annotation_completeness", COMPLETENESS_STATES, key=_sk(procurement_id, "completeness"))
    st.selectbox("evidence_state", EVIDENCE_STATES, key=_sk(procurement_id, "evidence_state"))
    findings = load_document_findings_for_annotation(procurement_id, crm_db)
    with st.expander(f"Сохранённые document findings ({len(findings)})"):
        if not findings:
            st.caption("Сохранённых document findings нет. Исследование автоматически не запускается.")
        for item in findings:
            st.markdown(
                f"- **{item.get('document_title') or item.get('source_document_type') or '—'}** · "
                f"parse=`{item.get('parse_status')}` · evidence=`{item.get('commercial_evidence_found')}` · "
                f"categories=`{item.get('matched_categories') or []}`"
            )


def _render_technical_details(assessment: dict | None, existing_annotation: dict | None) -> None:
    with st.expander("Технические данные"):
        st.markdown(f"assessment id: `{(assessment or {}).get('id')}`")
        st.markdown(f"inference_run_id: `{(assessment or {}).get('inference_run_id')}`")
        st.markdown(f"MODEL source: `{(assessment or {}).get('model_provenance')}`")
        st.markdown(
            f"prompt/model: `{(assessment or {}).get('model_version')}` / "
            f"`{(assessment or {}).get('prompt_version') or (assessment or {}).get('inference_prompt_version')}`"
        )
        if assessment and assessment.get("raw_model_json"):
            st.code(json.dumps(assessment["raw_model_json"], ensure_ascii=False, indent=2)[:4000])
        if assessment and assessment.get("validated_model_result"):
            st.markdown("**VALIDATED:**")
            st.code(json.dumps(assessment["validated_model_result"], ensure_ascii=False, indent=2)[:4000])
        if assessment and assessment.get("validation_errors"):
            st.markdown(f"validation_errors: `{assessment['validation_errors']}`")
        if existing_annotation:
            st.markdown(f"annotation v{existing_annotation.get('annotation_version')}")


def _build_workbench_payload(procurement_id: int, assessment: dict | None, created_by: str) -> dict:
    opps = list(st.session_state.get(_sk(procurement_id, "opps"), []))
    rejected = list(st.session_state.get(_sk(procurement_id, "rejected"), []))
    has_rejects = bool(rejected)
    has_adds = any(o.get("expert_action") == "ADD" for o in opps)
    absence = bool(st.session_state.get(_sk(procurement_id, "absence_confirmed")))
    has_unreviewed = any(
        row.get("model_opportunity_index") is not None and not row.get("expert_reviewed")
        for row in [*opps, *rejected]
    )
    completeness = st.session_state.get(_sk(procurement_id, "completeness"), "PARTIAL")
    if completeness == "PARTIAL" or has_unreviewed:
        verdict = "PARTIAL_REVIEW"
    elif has_rejects or has_adds:
        verdict = "WRONG" if has_rejects else "PARTIALLY_CORRECT"
    elif absence and not opps:
        verdict = "CORRECT"
    else:
        verdict = "CORRECT"
    payload = _assemble_payload(
        assessment=assessment,
        expert_verdict=verdict,
        expert_form="UNKNOWN",
        expert_obj_type=st.session_state.get(_sk(procurement_id, "obj_type"), "").strip(),
        expert_obj_subtype=st.session_state.get(_sk(procurement_id, "obj_subtype"), "").strip(),
        expert_work_stage=st.session_state.get(_sk(procurement_id, "work_stage"), "").strip(),
        expert_commercial_verdict="ACTIONABLE",
        expert_medal=None,
        medal_reason=None,
        medal_comment="",
        error_reasons=["MISSING_CATEGORY"] if has_adds else (["EXTRA_CATEGORY"] if has_rejects else []),
        expert_comment="",
        opps=opps,
        rejected=rejected,
        proposals=[],
        created_by=created_by,
    )
    payload["training_evidence_quality"] = _training_evidence_quality(assessment)
    payload["expert_category_absence_confirmed"] = absence and not opps
    payload["annotation_review_scope"] = st.session_state.get(_sk(procurement_id, "review_scope"), "CATEGORY_ONLY")
    payload["annotation_completeness"] = completeness
    payload["evidence_state"] = st.session_state.get(_sk(procurement_id, "evidence_state"), "SUFFICIENT")
    states = []
    for row in [*opps, *rejected]:
        if row.get("model_opportunity_index") is None:
            continue
        states.append({
            "model_opportunity_index": row.get("model_opportunity_index"),
            "category_code": row.get("category_code"),
            "reviewed": bool(row.get("expert_reviewed")),
            "decision": row.get("expert_action") if row.get("expert_reviewed") else None,
        })
    payload["model_category_review_state"] = sorted(states, key=lambda row: row["model_opportunity_index"])
    payload["reviewed_model_categories"] = [row for row in states if row["reviewed"]]
    payload["training_eligible"] = not training_eligibility_reasons(payload, assessment)
    payload["document_review_priorities"] = _document_priority_payload(procurement_id)
    return payload


def _document_priority_payload(procurement_id: int) -> list[dict]:
    priorities = st.session_state.get(_sk(procurement_id, "document_priorities"), {})
    return [
        {"document_key": key, "priority": priority}
        for key, priority in sorted(priorities.items())
        if priority in {"first", "second"}
    ]


def _persist(
    procurement_id: int,
    payload: dict,
    assessment: dict | None,
    created_by: str,
    crm_db: Any,
    *,
    save_and_next: bool,
) -> None:
    try:
        new_id = save_expert_annotation(procurement_id, payload, created_by, crm_db)
        write_audit_row(
            procurement_id=procurement_id,
            model_raw=(
                (assessment.get("validated_model_result") if assessment else None)
                or (assessment.get("normalized_result") if assessment else None)
            ),
            annotation_payload=payload,
            crm_db=crm_db,
        )
        st.session_state.pop(_sk(procurement_id, "fast_init"), None)
        st.success(f"✅ Разметка сохранена (id={new_id})")
        if save_and_next:
            st.session_state[GO_NEXT_KEY] = True
            st.session_state[GO_NEXT_FROM_KEY] = procurement_id
        st.rerun()
    except Exception as exc:
        st.error(f"❌ Ошибка сохранения: {exc}")
