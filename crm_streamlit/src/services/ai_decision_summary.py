"""Read-only compact AI decision summary from existing V3 assessment fields."""
from __future__ import annotations

from typing import Any

from src.services.annotation_category_gate import (
    IN_CATEGORY,
    OUT_OF_CATEGORY,
    UNCERTAIN,
    derive_model_stage1_scope,
)
from src.services.commercial_routing_v3.model_ui_projection import (
    business_view_from_assessment,
    model_view_from_assessment,
)
from src.services.expert_commercial_entry import model_commercial_entry_hint
from src.services.expert_medal_stage import model_medal_hint
from src.services.expert_object_taxonomy import model_object_hints
from src.services.expert_procurement_mode import model_procurement_mode_hint

UNDEFINED = "Не определено"

SCOPE_LABELS = {
    IN_CATEGORY: "В товарных категориях",
    OUT_OF_CATEGORY: "Вне товарных категорий",
    UNCERTAIN: "Не уверен",
}


def _fmt(value: Any) -> str:
    if value is None:
        return UNDEFINED
    text = str(value).strip()
    return text if text else UNDEFINED


def build_ai_decision_summary(assessment: dict | None) -> dict[str, Any]:
    """Structured read-only AI decisions for the primary card surface."""
    model = model_view_from_assessment(assessment)
    business = business_view_from_assessment(assessment)
    hints = model_object_hints(assessment)
    scope, codes = derive_model_stage1_scope(assessment)
    mode = model_procurement_mode_hint(assessment)
    entry = model_commercial_entry_hint(assessment)
    medal = model_medal_hint(assessment) or business.get("effective_medal") or business.get(
        "business_candidate_medal"
    )

    categories: list[str] = []
    subcategories: list[str] = []
    for hyp in model.get("hypotheses") or []:
        if not isinstance(hyp, dict):
            continue
        if hyp.get("category"):
            categories.append(str(hyp["category"]))
        if hyp.get("subcategory"):
            subcategories.append(str(hyp["subcategory"]))
    for code in codes:
        if code not in categories:
            categories.append(code)

    fields = [
        ("Объект", _fmt(model.get("object_type") or hints.get("object_type"))),
        ("Подтип объекта", _fmt(model.get("object_subtype") or hints.get("object_subtype"))),
        ("Этап / вид работ", _fmt(model.get("work_stage"))),
        ("Режим закупки", _fmt(model.get("procurement_form") or mode)),
        ("Товарная принадлежность", _fmt(SCOPE_LABELS.get(scope) if scope else None)),
        ("Категория", _fmt(", ".join(categories) if categories else None)),
        ("Подкатегория", _fmt(", ".join(subcategories) if subcategories else None)),
        ("Коммерческая применимость", _fmt(entry or business.get("business_scope_status"))),
        ("Medal", _fmt(medal)),
        ("Уверенность", _fmt(model.get("overall_confidence"))),
    ]
    return {
        "title": "ИИ предложил",
        "provenance": model.get("provenance"),
        "fields": fields,
        "read_only": True,
    }


def format_ai_decision_lines(assessment: dict | None) -> list[str]:
    summary = build_ai_decision_summary(assessment)
    return [f"{label}: {value}" for label, value in summary["fields"]]
