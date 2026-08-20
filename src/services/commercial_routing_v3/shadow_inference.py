"""Phase 6A SHADOW inference API.

Calls the same production Qwen/Ollama prompt path, persists immutable RAW+validated
inference runs, and MUST NOT mutate production assessments, opportunities, or visibility.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Set

from src.services.ai_assessment_runner import (
    OllamaJsonParseError,
    call_ollama_qwen_bundle,
)
from src.services.commercial_routing_v3.engine import CommercialRoutingV3Engine
from src.services.commercial_routing_v3.model_inference_runs import (
    RUN_KIND_SHADOW,
    InferenceRunRecord,
    capture_and_persist_inference_run,
)
from src.services.commercial_routing_v3.prompt import PROMPT_VERSION

logger = logging.getLogger("commercial_routing_v3.shadow_inference")


def _input_hash(model_input: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(model_input, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def run_shadow_inference(
    crm_db,
    *,
    procurement_id: int,
    procurement: Dict[str, Any],
    model_input: Optional[Dict[str, Any]] = None,
    allowed_categories: Optional[Set[str]] = None,
    allowed_subcategories: Optional[Dict[str, Set[str]]] = None,
    acquire_gpu: bool = True,
    dry_run_persist: bool = False,
    compute_business_preview: bool = True,
) -> Dict[str, Any]:
    """Run one SHADOW inference for a procurement.

    Side effects allowed:
      - INSERT into crm_v3_model_inference_runs (append-only)

    Side effects forbidden:
      - procurement_ai_assessments writes
      - opportunity CURRENT writes
      - torgi visibility changes
      - expert annotation writes
    """
    engine = CommercialRoutingV3Engine(crm_db=crm_db)
    registry, allowed, subs = engine.load_registry()
    cats = set(allowed_categories or allowed)
    submap = allowed_subcategories if allowed_subcategories is not None else subs

    prompt = engine.build_prompt_context(procurement)
    mi = model_input if isinstance(model_input, dict) else {}
    ih = _input_hash(mi) if mi else _input_hash({"procurement_id": procurement_id, "prompt": prompt[:200]})

    raw_text: Optional[str] = None
    parsed: Optional[Dict[str, Any]] = None
    meta: Dict[str, Any] = {}
    retry_count = 0
    model_call_failed = False
    parse_error: Optional[str] = None

    try:
        bundle = call_ollama_qwen_bundle(
            prompt,
            procurement_id=procurement_id,
            crm_db=crm_db,
            input_hash=ih,
            prompt_version=PROMPT_VERSION,
            persist_dry_run=True,  # do not upsert attempt telemetry as production side-effect path
            acquire_gpu=acquire_gpu,
        )
        if bundle is None:
            model_call_failed = True
        else:
            raw_text = bundle.raw_text
            parsed = bundle.parsed
            meta = dict(bundle.meta)
            retry_count = int(bundle.retry_count)
    except OllamaJsonParseError as exc:
        parse_error = str(exc)
        raw_text = getattr(exc, "raw_text", None)
        meta = dict(getattr(exc, "meta", None) or {})
        retry_count = int(getattr(exc, "retry_count", 0) or 0)

    run = capture_and_persist_inference_run(
        crm_db,
        procurement_id=procurement_id,
        run_kind=RUN_KIND_SHADOW,
        prompt=prompt,
        raw_text=raw_text,
        parsed=parsed,
        parse_error=parse_error,
        model_call_failed=model_call_failed,
        ollama_metadata=meta,
        retry_count=retry_count,
        allowed_categories=cats,
        allowed_subcategories=submap,
        model_name=str(meta.get("model") or "qwen2.5:7b"),
        prompt_version=PROMPT_VERSION,
        dry_run=dry_run_persist,
    )

    business_preview: Optional[Dict[str, Any]] = None
    if (
        compute_business_preview
        and run.validation_status == "VALIDATED_SUCCESS"
        and isinstance(run.validated_model_result, dict)
    ):
        # Analysis-only: never persisted to production assessment/opportunity tables.
        decision = engine.route_with_ai(procurement, run.validated_model_result)
        business_preview = {
            "routing_version": getattr(decision, "routing_version", None),
            "hypothesis_count": len(getattr(decision, "commercial_category_hypotheses", None) or []),
            "empty_hypothesis_status": getattr(decision, "empty_hypothesis_status", None),
            "overall_research_action": str(getattr(decision, "overall_research_action", None)),
        }

    return {
        "procurement_id": procurement_id,
        "inference_run_id": run.id,
        "run_kind": RUN_KIND_SHADOW,
        "parse_status": run.parse_status,
        "validation_status": run.validation_status,
        "raw_model_sha256": run.raw_model_sha256,
        "validated_model_sha256": run.validated_model_sha256,
        "validation_errors": list(run.validation_errors or []),
        "business_preview": business_preview,
        "production_assessment_mutated": False,
        "opportunities_mutated": False,
        "visibility_mutated": False,
        "run": run,
    }


def run_shadow_batch(
    crm_db,
    cases: List[Dict[str, Any]],
    *,
    acquire_gpu: bool = True,
    dry_run_persist: bool = False,
) -> Dict[str, Any]:
    """Run SHADOW for a list of {procurement_id, procurement[, model_input]} cases."""
    results = []
    for case in cases:
        pid = int(case["procurement_id"])
        procurement = case["procurement"]
        out = run_shadow_inference(
            crm_db,
            procurement_id=pid,
            procurement=procurement,
            model_input=case.get("model_input"),
            acquire_gpu=acquire_gpu,
            dry_run_persist=dry_run_persist,
        )
        results.append(out)
    return {
        "count": len(results),
        "results": results,
        "production_assessments_mutated": 0,
        "opportunities_mutated": 0,
        "visibility_mutated": 0,
    }
