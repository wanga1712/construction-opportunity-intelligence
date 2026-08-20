"""Field provenance classes for Phase 6B namespace separation.

MODEL means the semantic value exists in validated_model_result and originates
from Qwen RAW (after schema validation only).

Do NOT classify a Python aggregation as MODEL merely because inputs came from
the model — use MODEL_DERIVED for that case.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping, Optional

# Canonical provenance classes
MODEL_VALIDATED = "MODEL_VALIDATED"
MODEL_DERIVED = "MODEL_DERIVED"  # deterministic transform of validated model fields only
BUSINESS_RULE = "BUSINESS_RULE"
CONTEXT_PRIOR = "CONTEXT_PRIOR"
SOURCE_DATA = "SOURCE_DATA"
EXPERT = "EXPERT"
UI_DERIVED = "UI_DERIVED"
UNKNOWN_LEGACY = "UNKNOWN_LEGACY"

PROVENANCE_CLASSES = frozenset(
    {
        MODEL_VALIDATED,
        MODEL_DERIVED,
        BUSINESS_RULE,
        CONTEXT_PRIOR,
        SOURCE_DATA,
        EXPERT,
        UI_DERIVED,
        UNKNOWN_LEGACY,
    }
)

# Human labels for UI (Russian)
PROVENANCE_UI_LABEL = {
    MODEL_VALIDATED: "Модель вернула",
    MODEL_DERIVED: "Рассчитано из ответа модели",
    BUSINESS_RULE: "Бизнес-правило",
    CONTEXT_PRIOR: "Контекстный prior",
    SOURCE_DATA: "Исходные данные",
    EXPERT: "Эксперт",
    UI_DERIVED: "Отображение UI",
    UNKNOWN_LEGACY: "Старая оценка — исходный ответ модели не сохранён",
}


def ui_label(provenance: Optional[str]) -> str:
    key = str(provenance or UNKNOWN_LEGACY).upper()
    return PROVENANCE_UI_LABEL.get(key, PROVENANCE_UI_LABEL[UNKNOWN_LEGACY])


def build_field_provenance(
    *,
    model_validated: Optional[Mapping[str, Any]] = None,
    has_inference_run: bool = False,
    overall_confidence_source: str = MODEL_DERIVED,
) -> Dict[str, str]:
    """Deterministic provenance map for important display/business fields."""
    mv = dict(model_validated or {})
    oc = mv.get("object_classification") if isinstance(mv.get("object_classification"), dict) else {}
    hyps = mv.get("commercial_category_hypotheses") if isinstance(mv.get("commercial_category_hypotheses"), list) else []

    if not has_inference_run:
        unknown = UNKNOWN_LEGACY
        return {
            "object_type": unknown,
            "object_subtype": unknown,
            "project_stage": unknown,
            "procurement_type": unknown,
            "category": unknown,
            "subcategory": unknown,
            "opportunity_track": unknown,
            "category_confidence": unknown,
            "overall_confidence": unknown,
            "route_profile": BUSINESS_RULE,
            "business_scope_status": BUSINESS_RULE,
            "candidate_score": BUSINESS_RULE,
            "candidate_medal": BUSINESS_RULE,
            "effective_medal": BUSINESS_RULE,
            "reason_evidence": unknown,
        }

    has_oc = bool(oc)
    has_hyps = bool(hyps)
    has_form = mv.get("procurement_form") is not None

    return {
        "object_type": MODEL_VALIDATED if has_oc and oc.get("object_type") is not None else MODEL_VALIDATED,
        "object_subtype": MODEL_VALIDATED if has_oc else MODEL_VALIDATED,
        "project_stage": MODEL_VALIDATED if has_oc else MODEL_VALIDATED,  # maps work_stage
        "procurement_type": MODEL_VALIDATED if has_form else MODEL_VALIDATED,  # maps procurement_form
        "category": MODEL_VALIDATED if has_hyps else MODEL_VALIDATED,
        "subcategory": MODEL_VALIDATED,
        "opportunity_track": MODEL_VALIDATED,
        "category_confidence": MODEL_VALIDATED,
        "overall_confidence": overall_confidence_source,  # usually MODEL_DERIVED (max of hyps)
        "route_profile": BUSINESS_RULE,
        "business_scope_status": BUSINESS_RULE,
        "candidate_score": BUSINESS_RULE,
        "candidate_medal": BUSINESS_RULE,
        "effective_medal": BUSINESS_RULE,
        "reason_evidence": MODEL_VALIDATED if has_hyps else BUSINESS_RULE,
        "contextual_prior_category": CONTEXT_PRIOR,
    }


def annotate_hypotheses_provenance(
    hyps: list,
    *,
    default: str = MODEL_VALIDATED,
) -> list:
    """Return shallow copies with provenance set; never invent categories."""
    out = []
    for h in hyps or []:
        if not isinstance(h, dict):
            continue
        row = dict(h)
        rc = list(row.get("reason_codes") or [])
        if "object_mode_contextual_prior" in rc or row.get("evidence_role") == "CONTEXTUAL_RESEARCH_PRIOR":
            if "okpd_prior" in rc or "title_signal" in rc:
                row["provenance"] = CONTEXT_PRIOR
            else:
                row["provenance"] = CONTEXT_PRIOR
        else:
            row.setdefault("provenance", default)
        out.append(row)
    return out


def merge_provenance(
    base: MutableMapping[str, str],
    updates: Mapping[str, str],
) -> Dict[str, str]:
    out = dict(base)
    out.update({k: str(v) for k, v in updates.items()})
    return out
