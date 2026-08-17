"""Expert annotation form for AI tab.

Public functions:
    render_correct_fast_path(procurement_id, assessment, existing_annotation,
                             crm_db, created_by, on_save_next) -> dict | None
    render_expert_full_form(procurement_id, expert_verdict, assessment, existing_annotation,
                            categories, expert_object_types,
                            expert_work_stages, expert_object_subtypes,
                            crm_db, created_by) -> dict | None

Both return a validated annotation payload dict when the user clicks Save,
or None while the form is being filled.

Payload schema (schema_version=1):
{
  "schema_version": 1,
  "model_assessment_id": int,        # FK → procurement_ai_assessments.id
  "expert_verdict": "CORRECT|PARTIALLY_CORRECT|WRONG",

  # Expert-authored context (NOT MODEL RAW, NOT production canonical)
  "expert_procurement_form": str | null,
  "expert_object_type": str | null,
  "expert_object_subtype": str | null,
  "expert_work_stage": str | null,

  # Commercial verdict + medal
  "expert_commercial_verdict": "ACTIONABLE|NO_COMMERCIAL_ENTRY",
  "expert_medal": "GOLD|SILVER|BRONZE|WOOD|NCE|null",
  "medal_reason": str | null,
  "medal_comment": str,

  # Error taxonomy (multi-select)
  "error_reasons": list[str],
  "expert_comment": str,

  # Final expert ranked list (KEEP, ADD, MODIFY — excludes REJECT)
  "opportunities": [
    {
      "expert_rank": int,
      "expert_action": "KEEP|ADD|MODIFY",
      "category_code": str,
      "subcategory_code": str | null,
      "opportunity_track": str,      # OpportunityTrack canonical code
      "hypothesis_reasons": list[str],
      "expected_document_sources": list[str],
      "model_opportunity_snapshot": dict | null,
      "model_opportunity_index": int | null,
      "comment": str,
    }, ...
  ],

  # Rejected model hypotheses (negative training evidence)
  "rejected_model_opportunities": [
    {
      "expert_action": "REJECT",
      "category_code": str,
      "subcategory_code": str | null,
      "opportunity_track": str,
      "rejection_reason": str,
      "model_opportunity_snapshot": dict,
      "model_opportunity_index": int,
      "comment": str,
    }, ...
  ],

  # Taxonomy proposals for missing values
  "taxonomy_proposals": list[dict],
}
"""
from __future__ import annotations

import streamlit as st
from typing import Any

from src.domain.commercial_routing_v3 import OpportunityTrack, ProcurementForm

# ─────────────────────────────────────────────────────────────────────────────
# Constants / labels
# ─────────────────────────────────────────────────────────────────────────────

_TRACK_OPTIONS: list[str] = [track.value for track in OpportunityTrack]

_TRACK_LABELS: dict[str, str] = {
    "EMBEDDED_MATERIAL":   "Встраиваемый материал",
    "DIRECT_SUPPLY":       "Прямая поставка",
    "DESIGN_REQUIREMENT":  "Требование проекта",
    "DESIGN_INFLUENCE":    "Влияние на проект",
    "NO_COMMERCIAL_ENTRY": "Нет коммерческого входа",
    "UNKNOWN":             "Неизвестно",
}

_FORM_OPTIONS: list[str] = [f.value for f in ProcurementForm]
_FORM_LABELS: dict[str, str] = {
    "DIRECT_GOODS_PURCHASE":      "Прямая поставка товара",
    "CONSTRUCTION_WORKS":         "Строительные / ремонтные работы",
    "DESIGN_AND_BUILD":           "Проектирование + строительство",
    "DESIGN_EXPERTISE_AND_BUILD": "Проектирование / экспертиза + строительство",
    "DESIGN_ONLY":                "Только проектирование",
    "SURVEY_AND_DESIGN":          "Изыскания + проектирование",
    "WORKS_OTHER":                "Другие работы",
    "SERVICES_OTHER":             "Другие услуги",
    "UNKNOWN":                    "Не определено",
}

_ERROR_REASONS: list[tuple[str, str]] = [
    ("WRONG_PROCUREMENT_SUBJECT", "Неверный предмет закупки"),
    ("WRONG_PROCUREMENT_FORM", "Неверная форма закупки"),
    ("WRONG_OBJECT", "Неверный объект"),
    ("WRONG_WORK_STAGE", "Неверная стадия работ"),
    ("CONTEXT_AS_PRODUCT", "Контекст ошибочно принят за продукт"),
    ("MISSING_CATEGORY", "Пропущена коммерческая категория"),
    ("EXTRA_CATEGORY", "Лишняя коммерческая категория"),
    ("WRONG_CATEGORY_PRIORITY", "Неверный приоритет категории"),
    ("WRONG_SUBCATEGORY", "Неверная подкатегория"),
    ("WRONG_COMMERCIAL_TRACK", "Неверный коммерческий track"),
    ("OKPD_TOO_BROAD", "ОКПД слишком широкий"),
    ("ACCESSORY_AS_PRIMARY_PRODUCT", "Аксессуар принят за основной продукт"),
    ("OUTSIDE_SELLABLE_REGISTRY", "Вне продаваемого реестра"),
    ("OTHER", "Другое"),
]

_HYPOTHESIS_REASONS: list[tuple[str, str]] = [
    ("DIRECT_TITLE_EVIDENCE", "Прямое указание в названии"),
    ("DIRECT_PRODUCT_EVIDENCE", "Прямое указание на продукт"),
    ("OBJECT_TYPE_EXPERT_PRIOR", "Тип объекта (экспертный prior)"),
    ("WORK_STAGE_EXPERT_PRIOR", "Стадия работ (экспертный prior)"),
    ("EXPECTED_IN_ESTIMATE", "Ожидается в смете"),
    ("EXPECTED_IN_SPECIFICATION", "Ожидается в спецификации"),
    ("EXPECTED_IN_PROJECT_DOCUMENTATION", "Ожидается в проектной документации"),
    ("EXPERT_COMMERCIAL_KNOWLEDGE", "Коммерческий опыт эксперта"),
    ("OTHER", "Другое"),
]

_DOC_SOURCES: list[tuple[str, str]] = [
    ("TECHNICAL_TASK",       "Техническое задание"),
    ("SPECIFICATION",        "Спецификация"),
    ("ESTIMATE",             "Смета"),
    ("BILL_OF_QUANTITIES",   "Ведомость объёмов работ"),
    ("PROJECT_DOCUMENTATION","Проектная документация"),
    ("CONTRACT",             "Договор / контракт"),
    ("OTHER",                "Иное"),
]

_MEDAL_OPTIONS  = ["GOLD", "SILVER", "BRONZE", "WOOD"]
_MEDAL_LABELS   = {"GOLD": "🥇 Золото", "SILVER": "🥈 Серебро",
                   "BRONZE": "🥉 Бронза", "WOOD": "🪵 Дерево",
                   "NCE": "⛔ Нет коммерческого входа"}

_MEDAL_REASONS: list[tuple[str, str]] = [
    ("INSUFFICIENT_TIME", "Недостаточно времени"),
    ("COMMERCIAL_WINDOW_CLOSED", "Коммерческое окно закрыто"),
    ("WRONG_CATEGORY", "Неверная категория"),
    ("WRONG_PRODUCT", "Неверный продукт"),
    ("WEAK_COMMERCIAL_FIT", "Слабое коммерческое соответствие"),
    ("HIGH_COMMERCIAL_FIT", "Высокое коммерческое соответствие"),
    ("GOOD_OBJECT", "Хороший объект"),
    ("BAD_OBJECT", "Плохой объект"),
    ("GOOD_EXECUTION_WINDOW", "Хорошее окно исполнения"),
    ("BAD_EXECUTION_WINDOW", "Плохое окно исполнения"),
    ("LOW_VALUE", "Низкая ценность"),
    ("OTHER", "Другое"),
]

_REJECTION_REASONS: list[tuple[str, str]] = [
    ("WRONG_CATEGORY",     "Категория не относится к объекту"),
    ("FALSE_POSITIVE",     "Ложная сигнал-ошибка"),
    ("OUT_OF_PROFILE",     "Вне коммерческого профиля"),
    ("ALREADY_COVERED",    "Покрыта другой категорией"),
    ("INSIGNIFICANT",      "Несущественная возможность"),
]

_PROPOSAL_TYPES: list[tuple[str, str]] = [
    ("CATEGORY",       "Коммерческая категория"),
    ("SUBCATEGORY",    "Подкатегория"),
    ("OBJECT_SECTOR",  "Сектор объекта"),
    ("OBJECT_TYPE",    "Тип объекта"),
    ("OBJECT_SUBTYPE", "Подтип объекта"),
    ("WORK_STAGE",     "Стадия работ"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sk(procurement_id: int, suffix: str) -> str:
    """Stable Streamlit session-state key for this procurement card."""
    return f"ann_{procurement_id}_{suffix}"


def _idx(options: list[str], value: str | None, default: str) -> int:
    v = value if value else default
    if v not in options:
        return 0
    return options.index(v)


def _build_opportunity_draft_from_model(
    assessment: dict | None,
) -> list[dict]:
    """Pre-populate expert opportunity list from MODEL RAW hypotheses.

    Each model hypothesis becomes an initial draft with expert_action='KEEP'.
    MODEL RAW is immutable — this is a copy, not a reference.
    """
    if not assessment:
        return []
    nr   = assessment.get("normalized_result") or {}
    opps = nr.get("category_opportunities") or []
    draft = []
    for idx, opp in enumerate(opps):
        draft.append({
            "expert_rank":    idx + 1,
            "expert_action":  "KEEP",
            "category_code":  opp.get("category_code", ""),
            "subcategory_code": opp.get("subcategory_code"),
            "opportunity_track": opp.get("opportunity_track", OpportunityTrack.EMBEDDED_MATERIAL),
            "hypothesis_reasons": [],
            "expected_document_sources": [],
            "model_opportunity_snapshot": {
                "category_code":    opp.get("category_code"),
                "subcategory_code": opp.get("subcategory_code"),
                "opportunity_track": opp.get("opportunity_track"),
                "candidate_level":  opp.get("candidate_level"),
                "candidate_score":  opp.get("candidate_score"),
            },
            "model_opportunity_index": idx,
            "comment": "",
        })
    return draft


def _init_draft(procurement_id: int, assessment: dict | None,
                existing_annotation: dict | None) -> None:
    """Initialise session-state draft once per card load."""
    sk_init = _sk(procurement_id, "draft_init")
    if st.session_state.get(sk_init):
        return
    if existing_annotation:
        p = existing_annotation.get("payload", {})
        st.session_state[_sk(procurement_id, "verdict")]   = p.get("expert_verdict", "CORRECT")
        st.session_state[_sk(procurement_id, "opps")]      = p.get("opportunities", [])
        st.session_state[_sk(procurement_id, "rejected")]  = p.get("rejected_model_opportunities", [])
        st.session_state[_sk(procurement_id, "proposals")] = p.get("taxonomy_proposals", [])
    else:
        # fresh draft seeded from MODEL hypotheses
        st.session_state[_sk(procurement_id, "verdict")]   = "CORRECT"
        st.session_state[_sk(procurement_id, "opps")]      = _build_opportunity_draft_from_model(assessment)
        st.session_state[_sk(procurement_id, "rejected")]  = []
        st.session_state[_sk(procurement_id, "proposals")] = []
    st.session_state[sk_init] = True


# ─────────────────────────────────────────────────────────────────────────────
# CORRECT fast path
# ─────────────────────────────────────────────────────────────────────────────

def render_correct_fast_path(
    procurement_id: int,
    assessment: dict | None,
    existing_annotation: dict | None,
    created_by: str,
) -> dict | None:
    """Render a minimal 'CORRECT' save form.

    Returns annotation payload dict on save, None otherwise.
    """
    st.success("✅ ИИ определил правильно")
    existing_payload = (existing_annotation or {}).get("payload", {})
    form_labels = [_FORM_LABELS.get(form, form) for form in _FORM_OPTIONS]
    previous_form = existing_payload.get("expert_procurement_form") or "UNKNOWN"
    selected_form_label = st.selectbox(
        "Форма закупки (экспертная):",
        options=form_labels,
        index=_idx(_FORM_OPTIONS, previous_form, "UNKNOWN"),
        key=_sk(procurement_id, "correct_form"),
        help="Выберите явно; значение модели не подставляется в экспертное поле.",
    )
    expert_form = _FORM_OPTIONS[form_labels.index(selected_form_label)]
    comment = st.text_input(
        "Комментарий (необязательно):",
        key=_sk(procurement_id, "correct_comment"),
    )
    if st.button("💾 Сохранить CORRECT", key=_sk(procurement_id, "save_correct")):
        return _build_correct_payload(assessment, expert_form, comment, created_by)
    return None


def _build_correct_payload(
    assessment: dict | None,
    expert_form: str,
    comment: str,
    created_by: str,
) -> dict:
    nr = (assessment or {}).get("normalized_result") or {}
    opps = nr.get("category_opportunities") or []
    opportunities = []
    for idx, opp in enumerate(opps):
        opportunities.append({
            "expert_rank":    idx + 1,
            "expert_action":  "KEEP",
            "category_code":  opp.get("category_code", ""),
            "subcategory_code": opp.get("subcategory_code"),
            "opportunity_track": opp.get("opportunity_track", "EMBEDDED_MATERIAL"),
            "hypothesis_reasons": [],
            "expected_document_sources": [],
            "model_opportunity_snapshot": {
                "category_code":    opp.get("category_code"),
                "subcategory_code": opp.get("subcategory_code"),
                "opportunity_track": opp.get("opportunity_track"),
                "candidate_level":  opp.get("candidate_level"),
                "candidate_score":  opp.get("candidate_score"),
            },
            "model_opportunity_index": idx,
            "comment": "",
        })
    return {
        "model_assessment_id": (assessment or {}).get("id"),
        "expert_verdict": "CORRECT",
        "expert_procurement_form": expert_form,
        "expert_object_type": None,
        "expert_object_subtype": None,
        "expert_work_stage": None,
        "expert_commercial_verdict": "ACTIONABLE",
        "expert_medal": None,
        "medal_reason": None,
        "medal_comment": "",
        "error_reasons": [],
        "expert_comment": comment.strip(),
        "opportunities": opportunities,
        "rejected_model_opportunities": [],
        "taxonomy_proposals": [],
        "created_by": created_by,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Full expert form
# ─────────────────────────────────────────────────────────────────────────────

def render_expert_full_form(
    procurement_id: int,
    expert_verdict: str,
    assessment: dict | None,
    existing_annotation: dict | None,
    categories: list[dict],
    expert_object_types: list[str],
    expert_work_stages: list[str],
    expert_object_subtypes: list[str],
    created_by: str,
) -> dict | None:
    """Render the full expert annotation form.

    Returns payload dict on save, None while editing.
    ``categories`` is from ``load_categories_for_selector``.
    ``expert_object_types/stages/subtypes`` are from previously saved expert annotations.
    """
    _init_draft(procurement_id, assessment, existing_annotation)

    existing_payload = (existing_annotation or {}).get("payload", {})

    with st.container(border=True):
        st.markdown("##### ✏️ Экспертная разметка")

        # ── Procurement form correction ────────────────────────────────────
        st.markdown("**Тип закупки**")
        nr = (assessment or {}).get("normalized_result") or {}
        form_opts_labels = [_FORM_LABELS.get(f, f) for f in _FORM_OPTIONS]
        # Expert truth is explicit. MODEL RAW is comparison context only and
        # must never initialise an editable expert value.
        default_form = existing_payload.get("expert_procurement_form") or "UNKNOWN"
        form_idx = _idx(_FORM_OPTIONS, default_form, "UNKNOWN")
        sel_form_label = st.selectbox(
            "Форма закупки:",
            options=form_opts_labels,
            index=form_idx,
            key=_sk(procurement_id, "form"),
        )
        expert_form = _FORM_OPTIONS[form_opts_labels.index(sel_form_label)]

        # ── Object / work stage (expert-authored, no canonical taxonomy) ───
        st.markdown("**Объект и стадия работ**")
        st.caption(
            f"🤖 ИИ предложил: объект = `{nr.get('object_type') or '—'}` · "
            f"подтип = `{nr.get('object_subtype') or '—'}` · "
            f"стадия = `{nr.get('project_stage') or '—'}`  \\n"
            "_Исправьте ниже если модель ошиблась. "
            "Значения сохранятся только в разметке, не в production routing._"
        )

        # expert_object_type — text_input with datalist-style suggestions note
        # Suggestions are human-authored values only.  MODEL RAW is displayed
        # above for comparison but must never enter the suggestion vocabulary.
        all_obj_types = sorted(set(expert_object_types))
        expert_obj_type = st.text_input(
            "Тип объекта (экспертный):",
            value=existing_payload.get("expert_object_type") or "",
            key=_sk(procurement_id, "obj_type"),
            help="Предыдущие значения экспертов: " + (", ".join(all_obj_types) if all_obj_types else "пока пусто"),
        )

        all_obj_subtypes = sorted(set(expert_object_subtypes))
        expert_obj_subtype = st.text_input(
            "Подтип объекта (экспертный):",
            value=existing_payload.get("expert_object_subtype") or "",
            key=_sk(procurement_id, "obj_subtype"),
            help="Предыдущие значения экспертов: " + (", ".join(all_obj_subtypes) if all_obj_subtypes else "пока пусто"),
        )

        all_stages = sorted(set(expert_work_stages))
        expert_work_stage = st.text_input(
            "Стадия работ (экспертная):",
            value=existing_payload.get("expert_work_stage") or "",
            key=_sk(procurement_id, "work_stage"),
            help="Предыдущие значения экспертов: " + (", ".join(all_stages) if all_stages else "пока пусто"),
        )

        # ── Error reasons ──────────────────────────────────────────────────
        st.markdown("**Почему ИИ ошибся?**")
        prev_errors: list[str] = existing_payload.get("error_reasons", [])
        err_codes   = [c for c, _ in _ERROR_REASONS]
        err_labels  = [lbl for _, lbl in _ERROR_REASONS]
        prev_err_labels = [_ERROR_REASONS[err_codes.index(c)][1] for c in prev_errors if c in err_codes]
        sel_err_labels = st.multiselect(
            "Причины ошибки:", options=err_labels,
            default=prev_err_labels,
            key=_sk(procurement_id, "err_reasons"),
        )
        error_reasons = [err_codes[err_labels.index(lbl)] for lbl in sel_err_labels]

        # ── Commercial verdict + medal ─────────────────────────────────────
        st.markdown("**Коммерческий вердикт**")
        prev_verdict = existing_payload.get("expert_commercial_verdict", "ACTIONABLE")
        verdict_opts = ["ACTIONABLE", "NO_COMMERCIAL_ENTRY"]
        verdict_labels = ["Есть коммерческий вход", "Нет коммерческого входа"]
        verdict_idx = verdict_opts.index(prev_verdict) if prev_verdict in verdict_opts else 0
        sel_verdict_label = st.radio(
            "Вердикт:",
            options=verdict_labels,
            index=verdict_idx,
            key=_sk(procurement_id, "com_verdict"),
            horizontal=True,
        )
        expert_commercial_verdict = verdict_opts[verdict_labels.index(sel_verdict_label)]

        expert_medal = None
        medal_reason = None
        medal_comment = ""
        if expert_commercial_verdict == "ACTIONABLE":
            prev_medal = existing_payload.get("expert_medal")
            med_cols = st.columns(len(_MEDAL_OPTIONS))
            for i, m in enumerate(_MEDAL_OPTIONS):
                with med_cols[i]:
                    if st.button(
                        _MEDAL_LABELS[m],
                        key=_sk(procurement_id, f"medal_{m}"),
                        type="primary" if st.session_state.get(_sk(procurement_id, "medal_sel")) == m or (prev_medal == m and not st.session_state.get(_sk(procurement_id, "medal_sel"))) else "secondary",
                    ):
                        st.session_state[_sk(procurement_id, "medal_sel")] = m
            expert_medal = st.session_state.get(_sk(procurement_id, "medal_sel")) or prev_medal
            if expert_medal:
                st.caption(f"Выбрана медаль: **{_MEDAL_LABELS.get(expert_medal, expert_medal)}**")
            reason_codes = [code for code, _ in _MEDAL_REASONS]
            reason_labels = [label for _, label in _MEDAL_REASONS]
            previous_reason = existing_payload.get("medal_reason")
            reason_index = _idx(reason_codes, previous_reason, "OTHER")
            selected_reason_label = st.selectbox(
                "Причина экспертной медали:",
                options=reason_labels,
                index=reason_index,
                key=_sk(procurement_id, "medal_reason"),
            )
            medal_reason = reason_codes[reason_labels.index(selected_reason_label)]
            medal_comment = st.text_input(
                "Комментарий к медали:",
                value=existing_payload.get("medal_comment", ""),
                key=_sk(procurement_id, "medal_comment"),
            )
        else:
            expert_medal = "NCE"
            st.caption("Экспертная медаль: **⛔ NCE**")
            medal_reason = "OTHER"

        # ── Opportunity editor ─────────────────────────────────────────────
        st.markdown("---")
        st.markdown("**Экспертные гипотезы (ranked)**")
        st.caption(
            "Порядок = очерёдность исследования: #1 искать первым.  "
            "REJECT сохраняется как отрицательный пример, не входит в рейтинг."
        )

        opps_draft: list[dict] = st.session_state[_sk(procurement_id, "opps")]
        rejected_draft: list[dict] = st.session_state[_sk(procurement_id, "rejected")]

        cat_codes  = [c["code"] for c in categories]
        cat_labels = [f"{c['code']}  ({c['name']})" for c in categories]

        # Render ranked accepted opportunities
        to_reject_idx: list[int] = []
        for i, opp in enumerate(opps_draft):
            with st.expander(
                f"#{i+1}  {opp.get('category_code', '—')}  "
                f"[{opp.get('expert_action', 'KEEP')}]",
                expanded=False,
            ):
                _render_opportunity_editor(
                    procurement_id, i, opp, categories, cat_codes, cat_labels,
                )
                col_move, col_rej = st.columns([3, 1])
                with col_move:
                    mc1, mc2 = st.columns(2)
                    if i > 0 and mc1.button("↑ Выше", key=_sk(procurement_id, f"up_{i}")):
                        opps_draft[i-1], opps_draft[i] = opps_draft[i], opps_draft[i-1]
                        _renumber(opps_draft)
                        st.rerun()
                    if i < len(opps_draft)-1 and mc2.button("↓ Ниже", key=_sk(procurement_id, f"dn_{i}")):
                        opps_draft[i], opps_draft[i+1] = opps_draft[i+1], opps_draft[i]
                        _renumber(opps_draft)
                        st.rerun()
                with col_rej:
                    if st.button("✕ REJECT", key=_sk(procurement_id, f"rej_{i}"), type="secondary"):
                        to_reject_idx.append(i)

        # Apply rejects
        if to_reject_idx:
            for ri in sorted(to_reject_idx, reverse=True):
                victim = opps_draft.pop(ri)
                victim["expert_action"] = "REJECT"
                victim["expert_rank"] = None
                rejected_draft.append(victim)
            _renumber(opps_draft)
            st.rerun()

        # Add new hypothesis
        if st.button("➕ Добавить гипотезу", key=_sk(procurement_id, "add_opp")):
            opps_draft.append({
                "expert_rank":    len(opps_draft) + 1,
                "expert_action":  "ADD",
                "category_code":  cat_codes[0] if cat_codes else "",
                "subcategory_code": None,
                "opportunity_track": OpportunityTrack.EMBEDDED_MATERIAL,
                "hypothesis_reasons": [],
                "expected_document_sources": [],
                "model_opportunity_snapshot": None,
                "model_opportunity_index": None,
                "comment": "",
            })
            st.rerun()

        # Show rejected model hypotheses
        if rejected_draft:
            st.markdown("**Отклонённые гипотезы ИИ (отрицательные примеры)**")
            for j, rej in enumerate(rejected_draft):
                with st.expander(
                    f"✕ {rej.get('category_code', '—')}  [REJECT]",
                    expanded=False,
                ):
                    rej_reason_opts = [c for c, _ in _REJECTION_REASONS]
                    rej_labels_all  = [lbl for _, lbl in _REJECTION_REASONS]
                    prev_rej_r = rej.get("rejection_reason", "")
                    rej_label_sel = st.selectbox(
                        "Причина отклонения:",
                        options=rej_labels_all,
                        index=_idx(rej_reason_opts, prev_rej_r, "WRONG_CATEGORY"),
                        key=_sk(procurement_id, f"rej_reason_{j}"),
                    )
                    rej["rejection_reason"] = rej_reason_opts[rej_labels_all.index(rej_label_sel)]
                    rej["comment"] = st.text_input(
                        "Комментарий к отклонению:",
                        value=rej.get("comment", ""),
                        key=_sk(procurement_id, f"rej_cmt_{j}"),
                    )
                    if st.button("↩ Вернуть в список", key=_sk(procurement_id, f"unrej_{j}")):
                        item = rejected_draft.pop(j)
                        item["expert_action"] = "KEEP"
                        item["expert_rank"] = len(opps_draft) + 1
                        opps_draft.append(item)
                        st.rerun()

        # ── Taxonomy proposals ─────────────────────────────────────────────
        st.markdown("---")
        _render_taxonomy_proposals_section(procurement_id)

        # ── Expert comment ─────────────────────────────────────────────────
        expert_comment = st.text_area(
            "Общий комментарий эксперта:",
            value=existing_payload.get("expert_comment", ""),
            key=_sk(procurement_id, "comment"),
            height=80,
        )

        # ── Save buttons ───────────────────────────────────────────────────
        b1, b2 = st.columns(2)
        save_clicked      = b1.button("💾 Сохранить", key=_sk(procurement_id, "save_full"))
        save_next_clicked = b2.button("💾 Сохранить и следующая →",
                                      key=_sk(procurement_id, "save_next_full"),
                                      type="primary")

        if save_clicked or save_next_clicked:
            payload = _assemble_payload(
                assessment=assessment,
                expert_verdict=expert_verdict,
                expert_form=expert_form,
                expert_obj_type=expert_obj_type.strip(),
                expert_obj_subtype=expert_obj_subtype.strip(),
                expert_work_stage=expert_work_stage.strip(),
                expert_commercial_verdict=expert_commercial_verdict,
                expert_medal=expert_medal,
                medal_reason=medal_reason,
                medal_comment=medal_comment.strip(),
                error_reasons=error_reasons,
                expert_comment=expert_comment.strip(),
                opps=opps_draft,
                rejected=rejected_draft,
                proposals=st.session_state[_sk(procurement_id, "proposals")],
                created_by=created_by,
            )
            # Signal SAVE+NEXT via extra flag in payload (orchestrator handles nav)
            if save_next_clicked:
                payload["_save_and_next"] = True
            return payload

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Sub-renderers
# ─────────────────────────────────────────────────────────────────────────────

def _render_opportunity_editor(
    procurement_id: int,
    idx: int,
    opp: dict,
    categories: list[dict],
    cat_codes: list[str],
    cat_labels: list[str],
) -> None:
    """In-place editor for one ranked opportunity entry."""
    if opp.get("expert_action") != "ADD":
        opp["expert_action"] = st.selectbox(
            "Действие эксперта:",
            options=["KEEP", "MODIFY"],
            index=1 if opp.get("expert_action") == "MODIFY" else 0,
            key=_sk(procurement_id, f"action_{idx}"),
        )
    else:
        st.caption("Действие эксперта: `ADD`")

    # Category
    opp_cat = opp.get("category_code", "")
    cat_idx = cat_codes.index(opp_cat) if opp_cat in cat_codes else 0
    sel_cat_label = st.selectbox(
        "Категория:", options=cat_labels, index=cat_idx,
        key=_sk(procurement_id, f"cat_{idx}"),
    )
    opp["category_code"] = cat_codes[cat_labels.index(sel_cat_label)]

    # Subcategory (free text for now)
    opp["subcategory_code"] = st.text_input(
        "Подкатегория (код):",
        value=opp.get("subcategory_code") or "",
        key=_sk(procurement_id, f"sub_{idx}"),
    ).strip() or None

    # Track
    track_options = list(_TRACK_OPTIONS)
    current_track = opp.get("opportunity_track")
    if current_track and current_track not in track_options:
        # Preserve an existing production value verbatim. Never coerce it to
        # UNKNOWN or the first local option merely because the UI is older.
        track_options.append(current_track)
    trk_labels = [_TRACK_LABELS.get(t, f"{t} (существующее значение)") for t in track_options]
    trk_idx = _idx(track_options, current_track, "EMBEDDED_MATERIAL")
    sel_trk = st.selectbox(
        "Тип входа (track):", options=trk_labels, index=trk_idx,
        key=_sk(procurement_id, f"trk_{idx}"),
    )
    opp["opportunity_track"] = track_options[trk_labels.index(sel_trk)]

    # Hypothesis reasons (multi-select)
    hr_codes  = [c for c, _ in _HYPOTHESIS_REASONS]
    hr_labels = [lbl for _, lbl in _HYPOTHESIS_REASONS]
    prev_hr   = opp.get("hypothesis_reasons", [])
    prev_hr_lbl = [_HYPOTHESIS_REASONS[hr_codes.index(c)][1] for c in prev_hr if c in hr_codes]
    sel_hr = st.multiselect(
        "Почему эксперт предполагает эту категорию:", options=hr_labels,
        default=prev_hr_lbl,
        key=_sk(procurement_id, f"hr_{idx}"),
    )
    opp["hypothesis_reasons"] = [hr_codes[hr_labels.index(lbl)] for lbl in sel_hr]

    # Expected document sources (multi-select)
    ds_codes  = [c for c, _ in _DOC_SOURCES]
    ds_labels = [lbl for _, lbl in _DOC_SOURCES]
    prev_ds   = opp.get("expected_document_sources", [])
    prev_ds_lbl = [_DOC_SOURCES[ds_codes.index(c)][1] for c in prev_ds if c in ds_codes]
    sel_ds = st.multiselect(
        "Где искать подтверждение:", options=ds_labels,
        default=prev_ds_lbl,
        key=_sk(procurement_id, f"ds_{idx}"),
    )
    opp["expected_document_sources"] = [ds_codes[ds_labels.index(lbl)] for lbl in sel_ds]

    # Comment
    opp["comment"] = st.text_input(
        "Комментарий:", value=opp.get("comment", ""),
        key=_sk(procurement_id, f"cmt_{idx}"),
    )

    # Model reference (read-only display)
    snap = opp.get("model_opportunity_snapshot")
    if snap:
        st.caption(
            f"🤖 Model: `{snap.get('category_code', '—')}` "
            f"/ `{snap.get('opportunity_track', '—')}` "
            f"/ {snap.get('candidate_level', '—')}"
        )


def _render_taxonomy_proposals_section(procurement_id: int) -> None:
    """Optional taxonomy proposal form."""
    proposals: list[dict] = st.session_state[_sk(procurement_id, "proposals")]
    if proposals:
        st.markdown(f"**Предложения в taxonomy ({len(proposals)})**")
        for pi, prop in enumerate(proposals):
            st.markdown(
                f"- `{prop.get('proposal_type')}` → **{prop.get('proposed_name')}**"
                f"  _{prop.get('expert_comment', '')}_"
            )

    if st.button("➕ Предложить новое значение taxonomy",
                 key=_sk(procurement_id, "add_prop")):
        st.session_state[_sk(procurement_id, "show_prop_form")] = True

    if st.session_state.get(_sk(procurement_id, "show_prop_form")):
        pt_codes  = [c for c, _ in _PROPOSAL_TYPES]
        pt_labels = [lbl for _, lbl in _PROPOSAL_TYPES]
        sel_pt = st.selectbox(
            "Тип предложения:", options=pt_labels,
            key=_sk(procurement_id, "prop_type"),
        )
        prop_name = st.text_input(
            "Предлагаемое название/код:",
            key=_sk(procurement_id, "prop_name"),
        )
        prop_parent = st.text_input(
            "Родительская категория (если применимо):",
            key=_sk(procurement_id, "prop_parent"),
        )
        prop_cmt = st.text_input(
            "Комментарий:", key=_sk(procurement_id, "prop_cmt"),
        )
        if st.button("Добавить предложение", key=_sk(procurement_id, "prop_add_btn")):
            if prop_name.strip():
                proposals.append({
                    "proposal_type":           pt_codes[pt_labels.index(sel_pt)],
                    "proposed_name":           prop_name.strip(),
                    "proposed_parent_category": prop_parent.strip() or None,
                    "expert_comment":          prop_cmt.strip() or None,
                })
                st.session_state[_sk(procurement_id, "show_prop_form")] = False
                st.rerun()


def _renumber(opps: list[dict]) -> None:
    for i, o in enumerate(opps):
        o["expert_rank"] = i + 1


def _assemble_payload(
    *,
    assessment: dict | None,
    expert_verdict: str,
    expert_form: str,
    expert_obj_type: str,
    expert_obj_subtype: str,
    expert_work_stage: str,
    expert_commercial_verdict: str,
    expert_medal: str | None,
    medal_reason: str | None,
    medal_comment: str,
    error_reasons: list[str],
    expert_comment: str,
    opps: list[dict],
    rejected: list[dict],
    proposals: list[dict],
    created_by: str,
) -> dict:
    return {
        "model_assessment_id": (assessment or {}).get("id"),
        "expert_verdict": expert_verdict,
        "expert_procurement_form": expert_form or None,
        "expert_object_type":    expert_obj_type or None,
        "expert_object_subtype": expert_obj_subtype or None,
        "expert_work_stage":     expert_work_stage or None,
        "expert_commercial_verdict": expert_commercial_verdict,
        "expert_medal":   expert_medal,
        "medal_reason":   medal_reason,
        "medal_comment":  medal_comment,
        "error_reasons":  error_reasons,
        "expert_comment": expert_comment,
        "opportunities":  opps,
        "rejected_model_opportunities": rejected,
        "taxonomy_proposals": proposals,
        "created_by": created_by,
    }
