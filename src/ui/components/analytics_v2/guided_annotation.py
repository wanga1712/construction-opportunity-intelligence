"""Selector-first expert workflow backed by registries and human vocabulary."""
from __future__ import annotations

import re
from typing import Any

import streamlit as st

from src.domain.commercial_routing_v3 import OpportunityTrack
from src.services.expert_annotation_service import load_subcategories_for_categories
from src.ui.components.analytics_v2.card_tabs_ai_expert_form import _renumber, _sk

NEW_VALUE = "__NEW_VALUE__"
MEDAL_HELP = {
    "GOLD": "Высокий коммерческий потенциал / точно стоит отрабатывать",
    "SILVER": "Наш объект, коммерчески интересен",
    "BRONZE": "Потенциально интересен, но есть ограничения",
    "WOOD": "Наш профиль, но слабый коммерческий приоритет",
}


def normalize_taxonomy_text(value: str | None) -> str:
    """Normalize whitespace without changing a human label's letter case."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def equivalent_known_value(value: str | None, known_values: list[str]) -> str | None:
    needle = normalize_taxonomy_text(value).casefold()
    if not needle:
        return None
    return next(
        (known for known in known_values if normalize_taxonomy_text(known).casefold() == needle),
        None,
    )


def sync_category_draft(
    selected_codes: list[str],
    opportunities: list[dict],
    rejected: list[dict],
    model_rows: list[dict],
) -> None:
    """Make the shared opportunity draft exactly match explicit expert selection."""
    selected = set(selected_codes)
    model_by_code = {row.get("category_code"): row for row in model_rows}
    existing_by_code = {row.get("category_code"): row for row in opportunities}
    rejected_by_code = {row.get("category_code"): row for row in rejected}

    for code in selected_codes:
        row = existing_by_code.get(code)
        if row is None and code in rejected_by_code:
            row = rejected_by_code[code]
            rejected.remove(row)
        if row is None:
            model = model_by_code.get(code)
            row = {
                "category_code": code,
                "subcategory_code": None,
                "opportunity_track": (model or {}).get("opportunity_track", OpportunityTrack.EMBEDDED_MATERIAL),
                "hypothesis_reasons": [] if model else ["EXPERT_COMMERCIAL_KNOWLEDGE"],
                "expected_document_sources": [],
                "model_opportunity_snapshot": (model or {}).get("model_opportunity_snapshot"),
                "model_opportunity_index": (model or {}).get("model_opportunity_index"),
                "comment": "",
            }
            opportunities.append(row)
        row["expert_action"] = "KEEP" if code in model_by_code else "ADD"
        row["expert_reviewed"] = True
        row.pop("rejection_reason", None)

    for row in list(opportunities):
        code = row.get("category_code")
        if code in selected:
            continue
        opportunities.remove(row)
        if code in model_by_code:
            row.update({
                "expert_action": "REJECT",
                "expert_reviewed": True,
                "expert_rank": None,
                "rejection_reason": row.get("rejection_reason") or "WRONG_CATEGORY",
            })
            if not any(item.get("category_code") == code for item in rejected):
                rejected.append(row)
    _renumber(opportunities)


def _category_label(code: str, categories_by_code: dict[str, dict]) -> str:
    row = categories_by_code.get(code) or {}
    name = row.get("name") or code
    return f"{name} · {code}"


def render_category_selector(
    procurement_id: int,
    assessment: dict | None,
    categories: list[dict],
    model_rows: list[dict],
    crm_db: Any,
) -> None:
    st.markdown("##### 2. Что нам здесь интересно?")
    by_code = {row["code"]: row for row in categories}
    codes = list(by_code)
    opps = st.session_state[_sk(procurement_id, "opps")]
    rejected = st.session_state[_sk(procurement_id, "rejected")]
    selection_key = _sk(procurement_id, "guided_categories")
    if selection_key not in st.session_state:
        st.session_state[selection_key] = [
            row.get("category_code") for row in opps if row.get("category_code") in by_code
        ]
    if model_rows:
        st.caption("🤖 ИИ предложил — только для чтения")
        for row in model_rows:
            code = row["category_code"]
            label, accept, reject = st.columns([4, 1, 1])
            label.markdown(f"📦 {_category_label(code, by_code)}")
            if code not in by_code:
                accept.caption("Нет в активном реестре")
            elif accept.button("✓ Принять", key=_sk(procurement_id, f"guided_accept_{code}")):
                selected = list(st.session_state[selection_key])
                if code not in selected:
                    selected.append(code)
                sync_category_draft(selected, opps, rejected, model_rows)
                st.session_state[selection_key] = selected
                st.rerun()
            if reject.button("✕ Отклонить", key=_sk(procurement_id, f"guided_reject_{code}")):
                selected = [item for item in st.session_state[selection_key] if item != code]
                sync_category_draft([*selected, code], opps, rejected, model_rows)
                sync_category_draft(selected, opps, rejected, model_rows)
                st.session_state[selection_key] = selected
                st.rerun()
    else:
        st.caption("🤖 ИИ пока не оценил закупку")

    st.markdown("**👤 Эксперт**")
    st.session_state[_sk(procurement_id, "guided_category_names")] = [row["name"] for row in categories]
    selected = st.multiselect(
        "Категории",
        codes,
        key=selection_key,
        format_func=lambda code: _category_label(code, by_code),
        placeholder="Выберите одну или несколько категорий",
    )
    sync_category_draft(selected, opps, rejected, model_rows)

    subcategories = load_subcategories_for_categories(selected, crm_db)
    for code in selected:
        options = subcategories.get(code, [])
        sub_by_code = {row["code"]: row for row in options}
        st.session_state[_sk(procurement_id, f"guided_subcategory_names_{code}")] = [
            row["name"] for row in options
        ]
        opportunity = next(row for row in opps if row.get("category_code") == code)
        current = opportunity.get("subcategory_code")
        values = [None, *sub_by_code]
        index = values.index(current) if current in values else 0
        chosen = st.selectbox(
            f"Подкатегория — {by_code[code]['name']}",
            values,
            index=index,
            key=_sk(procurement_id, f"guided_subcategory_{code}"),
            format_func=lambda value: "Без подкатегории" if value is None else f"{sub_by_code[value]['name']} · {value}",
            placeholder="Выберите подкатегорию",
        )
        opportunity["subcategory_code"] = chosen
        if st.button(
            "+ Предложить новую подкатегорию",
            key=_sk(procurement_id, f"new_subcategory_toggle_{code}"),
        ):
            st.session_state[_sk(procurement_id, f"show_new_subcategory_{code}")] = True
        if st.session_state.get(_sk(procurement_id, f"show_new_subcategory_{code}")):
            st.text_input(
                f"Новая подкатегория — {by_code[code]['name']}",
                key=_sk(procurement_id, f"new_subcategory_text_{code}"),
            )

    if st.button("+ Предложить новую категорию", key=_sk(procurement_id, "new_category_toggle")):
        st.session_state[_sk(procurement_id, "show_new_category")] = True
    if st.session_state.get(_sk(procurement_id, "show_new_category")):
        st.text_input("Название новой категории", key=_sk(procurement_id, "new_category_text"))


def _render_vocabulary_selector(
    procurement_id: int,
    *,
    step: str,
    label: str,
    field: str,
    proposal_type: str,
    known_values: list[str],
    model_value: str | None,
    allow_empty: bool,
) -> None:
    st.session_state[_sk(procurement_id, f"{field}_known_values")] = list(known_values)
    st.markdown(f"##### {step}. {label}")
    if model_value:
        st.caption(f"🤖 ИИ предложил: {model_value} (только для чтения)")
        if st.button("✓ Принять предложение ИИ", key=_sk(procurement_id, f"accept_model_{field}")):
            clean_model = normalize_taxonomy_text(model_value)
            st.session_state[_sk(procurement_id, field)] = clean_model
            st.session_state[_sk(procurement_id, f"{field}_choice")] = clean_model
            st.rerun()

    current = normalize_taxonomy_text(st.session_state.get(_sk(procurement_id, field)))
    options = ([None] if allow_empty else []) + list(known_values) + [NEW_VALUE]
    initial = current if current in known_values else (None if allow_empty else (known_values[0] if known_values else NEW_VALUE))
    if current and current not in known_values:
        initial = NEW_VALUE
    choice = st.selectbox(
        label,
        options,
        index=options.index(initial),
        key=_sk(procurement_id, f"{field}_choice"),
        format_func=lambda value: (
            "Без уточнения" if value is None else
            f"+ Новое значение" if value == NEW_VALUE else value
        ),
        placeholder="Выберите...",
    )
    if choice == NEW_VALUE:
        entered = st.text_input(
            f"Новое значение — {label.lower()}",
            value=current if current not in known_values else "",
            key=_sk(procurement_id, f"{field}_new"),
        )
        equivalent = equivalent_known_value(entered, known_values)
        if equivalent:
            st.info(f"Такое значение уже есть: «{equivalent}». Будет использовано существующее.")
            st.session_state[_sk(procurement_id, field)] = equivalent
        else:
            st.session_state[_sk(procurement_id, field)] = normalize_taxonomy_text(entered)
        st.session_state[_sk(procurement_id, f"{field}_proposal_type")] = proposal_type
    else:
        st.session_state[_sk(procurement_id, field)] = choice or ""
        st.session_state.pop(_sk(procurement_id, f"{field}_proposal_type"), None)


def render_object_stage_selectors(
    procurement_id: int,
    *,
    obj_types: list[str],
    subtypes: list[str],
    stages: list[str],
    model_object_type: str | None,
    model_object_subtype: str | None,
    model_stage: str | None,
) -> None:
    _render_vocabulary_selector(procurement_id, step="3", label="Тип объекта", field="obj_type",
                                proposal_type="OBJECT_TYPE", known_values=obj_types,
                                model_value=model_object_type, allow_empty=False)
    _render_vocabulary_selector(procurement_id, step="3.1", label="Подтип / уточнение объекта", field="obj_subtype",
                                proposal_type="OBJECT_SUBTYPE", known_values=subtypes,
                                model_value=model_object_subtype, allow_empty=True)
    _render_vocabulary_selector(procurement_id, step="4", label="Стадия / вид работ", field="work_stage",
                                proposal_type="WORK_STAGE", known_values=stages,
                                model_value=model_stage, allow_empty=False)


def pending_guided_proposals(
    procurement_id: int,
    known_by_field: dict[str, list[str]],
    selected_category_codes: list[str],
) -> list[dict]:
    proposals: list[dict] = []
    category = normalize_taxonomy_text(st.session_state.get(_sk(procurement_id, "new_category_text")))
    known_categories = list(st.session_state.get(_sk(procurement_id, "guided_category_names"), []))
    if category and not equivalent_known_value(category, known_categories):
        proposals.append({"proposal_type": "CATEGORY", "proposed_name": category,
                          "proposed_parent_category": None, "expert_comment": None})
    for code in selected_category_codes:
        value = normalize_taxonomy_text(
            st.session_state.get(_sk(procurement_id, f"new_subcategory_text_{code}"))
        )
        known_subcategories = list(
            st.session_state.get(_sk(procurement_id, f"guided_subcategory_names_{code}"), [])
        )
        if value and not equivalent_known_value(value, known_subcategories):
            proposals.append({"proposal_type": "SUBCATEGORY", "proposed_name": value,
                              "proposed_parent_category": code, "expert_comment": None})
    for field, proposal_type in (("obj_type", "OBJECT_TYPE"), ("obj_subtype", "OBJECT_SUBTYPE"), ("work_stage", "WORK_STAGE")):
        if st.session_state.get(_sk(procurement_id, f"{field}_proposal_type")) != proposal_type:
            continue
        value = normalize_taxonomy_text(st.session_state.get(_sk(procurement_id, field)))
        if value and not equivalent_known_value(value, known_by_field[field]):
            proposals.append({"proposal_type": proposal_type, "proposed_name": value,
                              "proposed_parent_category": None, "expert_comment": None})
    return proposals
