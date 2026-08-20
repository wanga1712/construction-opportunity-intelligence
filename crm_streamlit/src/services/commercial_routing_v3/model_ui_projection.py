"""Phase 6B MODEL UI projection from validated_model_result only."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def model_view_from_assessment(assessment: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Build MODEL section payload.

    Authority:
      - proven: assessment.validated_model_result (via inference_run_id)
      - legacy: UNKNOWN_LEGACY — do not claim \"Модель предложила\"
    """
    a = assessment or {}
    provenance = a.get("model_provenance") or (
        "MODEL_VALIDATED" if a.get("inference_run_id") else "UNKNOWN_LEGACY"
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
            "procurement_form": None,
            "hypotheses": [],
            "overall_confidence": None,
            "overall_confidence_provenance": "UNKNOWN_LEGACY",
            "contains_rule_fields": False,
        }

    oc = mv.get("object_classification") if isinstance(mv.get("object_classification"), dict) else {}
    hyps_raw = mv.get("commercial_category_hypotheses") or []
    hyps: List[Dict[str, Any]] = []
    for h in hyps_raw:
        if not isinstance(h, dict):
            continue
        hyps.append(
            {
                "category": h.get("category_code") or h.get("commercial_category_code"),
                "subcategory": h.get("subcategory_code") or h.get("commercial_subcategory_code"),
                "opportunity_track": h.get("opportunity_track"),
                "confidence": h.get("confidence", h.get("category_confidence")),
                "reason_codes": list(h.get("reason_codes") or []),
                "provenance": "MODEL_VALIDATED",
            }
        )

    # MODEL_DERIVED aggregate — never labeled as raw model field.
    confs = [float(h["confidence"]) for h in hyps if h.get("confidence") is not None]
    overall = max(confs) if confs else None

    return {
        "provenance": "MODEL_VALIDATED",
        "label": "Модель",
        "object_type": oc.get("object_type"),
        "object_subtype": oc.get("object_subtype"),
        "work_stage": oc.get("work_stage"),
        "procurement_form": mv.get("procurement_form"),
        "hypotheses": hyps,
        "overall_confidence": overall,
        "overall_confidence_provenance": "MODEL_DERIVED",
        "contains_rule_fields": False,
        "raw_keys_present": sorted(mv.keys()),
    }


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
