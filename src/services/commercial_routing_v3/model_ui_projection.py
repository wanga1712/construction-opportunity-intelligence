"""Phase 6B MODEL UI projection from validated_model_result only."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.services.medal_semantics_v2 import record_is_current_model


def model_view_from_assessment(assessment: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Build MODEL section payload.

    Authority:
      - proven: assessment.validated_model_result (via inference_run_id)
      - legacy: UNKNOWN_LEGACY — do not claim \"Модель предложила\"
    """
    a = assessment or {}
    # MEDAL SEMANTICS V2: an old-prompt, stale or run-less row is legacy, so
    # the UI never claims "the model proposed this" for an obsolete result.
    provenance = a.get("model_provenance") or (
        "MODEL_VALIDATED" if record_is_current_model(a) else "UNKNOWN_LEGACY"
    )
    mv = a.get("validated_model_result")
    if not isinstance(mv, dict):
        mv = None

    if provenance == "UNKNOWN_LEGACY" or mv is None:
        return {
            "provenance": "UNKNOWN_LEGACY",
            "label": "Старая оценка — исходный ответ модели не сохранён",
            "object_type": None,
            "object_subtype": None,
            "work_stage": None,
            "object_stage": None,
            "service_type": None,
            "legacy_tender_stage": None,
            "procurement_form": None,
            "hypotheses": [],
            "overall_confidence": None,
            "overall_confidence_provenance": "UNKNOWN_LEGACY",
            "contains_rule_fields": False,
        }

    oc = mv.get("object_classification") if isinstance(mv.get("object_classification"), dict) else {}
    hyps_raw = mv.get("commercial_category_hypotheses") or mv.get("category_evaluations") or []
    hyps: List[Dict[str, Any]] = []
    for h in hyps_raw:
        if not isinstance(h, dict):
            continue
        c_code = h.get("category_code") or h.get("commercial_category_code")
        c_medal = h.get("category_model_medal") or h.get("opportunity_track")
        c_conf = h.get("category_model_score") or h.get("confidence") or h.get("category_confidence")
        if isinstance(c_conf, (int, float)) and c_conf > 1.0:
            c_conf = c_conf / 100.0
        reasons = list(h.get("reason_codes") or [])
        if not reasons and h.get("category_reason"):
            reasons = [h.get("category_reason")]
        hyps.append(
            {
                "category": c_code,
                "subcategory": h.get("subcategory_code") or h.get("commercial_subcategory_code"),
                "opportunity_track": c_medal,
                "confidence": c_conf,
                "reason_codes": reasons,
                "provenance": "MODEL_VALIDATED",
            }
        )

    # MODEL_DERIVED aggregate — never labeled as raw model field.
    confs = [float(h["confidence"]) for h in hyps if h.get("confidence") is not None]
    overall = max(confs) if confs else None
    if overall is None and mv.get("model_score") is not None:
        try:
            overall = float(mv.get("model_score")) / 100.0
        except Exception:
            pass

    return {
        "provenance": "MODEL_VALIDATED",
        "label": "Модель",
        "object_type": oc.get("object_type"),
        "object_subtype": oc.get("object_subtype"),
        "work_stage": oc.get("work_stage"),
        # OBJECT_STAGE / SERVICE_TYPE are deterministic routing axes — see
        # routing_axes_view_from_assessment(). The MODEL block only echoes a
        # value if the model itself returned one (today it does not).
        "object_stage": oc.get("object_stage"),
        "service_type": mv.get("service_type"),
        # Legacy tender/publication stage — never present it as «Стадия объекта».
        "legacy_tender_stage": (a.get("normalized_result") or {}).get("project_stage")
        if isinstance(a.get("normalized_result"), dict)
        else None,
        "procurement_form": mv.get("procurement_form"),
        "model_medal": mv.get("model_medal"),
        "model_score": mv.get("model_score"),
        "model_reason": mv.get("model_reason"),
        "found_facts": mv.get("found_facts") or [],
        "hypotheses": hyps,
        "overall_confidence": overall,
        "overall_confidence_provenance": "MODEL_DERIVED",
        "contains_rule_fields": False,
        "raw_keys_present": sorted(mv.keys()),
    }




def routing_axes_view_from_assessment(assessment: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Deterministic canonical routing axes for the card.

    Authority: BUSINESS_RULE — classify_object_stage() / classify_service_type()
    run on the persisted procurement form + title. These are the axes the UI must
    render as «Форма закупки / Стадия объекта / Характер работ / Тип услуги».

    ``legacy_tender_stage`` exposes the legacy compatibility key
    (``normalized_result.project_stage``) under an explicit legacy name so it can
    never be mistaken for the object lifecycle stage.
    """
    a = assessment or {}
    nr = a.get("normalized_result") if isinstance(a.get("normalized_result"), dict) else {}
    mv = a.get("validated_model_result") if isinstance(a.get("validated_model_result"), dict) else {}
    oc = mv.get("object_classification") if isinstance(mv.get("object_classification"), dict) else {}

    form = nr.get("procurement_form") or mv.get("procurement_form")
    object_stage = nr.get("object_stage") or oc.get("object_stage")
    service_type = nr.get("service_type") or mv.get("service_type")
    applicable = nr.get("object_stage_applicable")
    if applicable is None:
        applicable = str(form or "").upper() != "DIRECT_GOODS_PURCHASE"
    return {
        "provenance": "BUSINESS_RULE",
        "procurement_form": form,
        "object_stage": object_stage,
        "object_stage_applicable": bool(applicable),
        "work_stage": oc.get("work_stage") or nr.get("work_stage"),
        "service_type": service_type,
        "legacy_tender_stage": nr.get("project_stage"),
    }


def format_object_stage(axes: Dict[str, Any]) -> str:
    """Render the OBJECT_STAGE axis without substituting the legacy tender stage.

    ``DIRECT_GOODS_PURCHASE`` has no object lifecycle stage, so it renders as
    "не применимо" instead of an empty value that could be read as UNKNOWN.
    """
    if not axes.get("object_stage_applicable"):
        return "не применимо"
    return str(axes.get("object_stage") or "не определено")


def business_view_from_assessment(assessment: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """BUSINESS section — never labeled as model/AI result."""
    a = assessment or {}
    brr = a.get("business_rule_result") if isinstance(a.get("business_rule_result"), dict) else {}
    nr = a.get("normalized_result") if isinstance(a.get("normalized_result"), dict) else {}
    return {
        "route_profile": brr.get("route_profile") or nr.get("route_profile") or a.get("proposed_route_profile"),
        "business_scope_status": brr.get("business_scope_status") or nr.get("business_scope_status"),
        "contextual_prior_hypotheses": list(
            brr.get("contextual_prior_hypotheses")
            or nr.get("contextual_prior_hypotheses")
            or []
        ),
        "business_candidate_score": brr.get("business_candidate_score", nr.get("business_candidate_score", nr.get("candidate_score"))),
        "business_candidate_medal": brr.get("business_candidate_medal", nr.get("business_candidate_medal", nr.get("candidate_level"))),
        "effective_medal": brr.get("effective_medal", nr.get("effective_medal")),
        "provenance": "BUSINESS_RULE",
    }
