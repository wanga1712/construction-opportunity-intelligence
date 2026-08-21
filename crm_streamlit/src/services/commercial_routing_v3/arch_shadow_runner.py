"""SHADOW runners for Architecture A (two-pass) and B (extract+map)."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from src.services.commercial_routing_v3.arch_prompts import (
    PROMPT_A1,
    PROMPT_A2,
    PROMPT_B_EXTRACT,
    build_a1_classify_prompt,
    build_a2_category_prompt,
    build_b_extract_prompt,
)
from src.services.commercial_routing_v3.engine import CommercialRoutingV3Engine
from src.services.commercial_routing_v3.registry_extract_mapper import (
    PROVENANCE,
    build_registry_vocabulary,
    map_extracted_to_categories,
)
from src.services.commercial_routing_v3.shadow_inference import run_shadow_inference


def _d(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _list_str(v: Any) -> List[str]:
    if isinstance(v, list):
        return [str(x) for x in v if x]
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


def _cats(val: Dict[str, Any]) -> List[str]:
    hyps = val.get("commercial_category_hypotheses") or []
    if not isinstance(hyps, list):
        return []
    return [
        str(h.get("category_code"))
        for h in hyps
        if isinstance(h, dict) and h.get("category_code")
    ]


def _title_okpd(row: Dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("auction_name") or row.get("title") or ""),
        str(row.get("okpd_code") or ""),
        str(row.get("okpd_name") or ""),
    )


def run_architecture_a(
    crm_db,
    *,
    procurement_id: int,
    row: Dict[str, Any],
    acquire_gpu: bool = True,
) -> Dict[str, Any]:
    """Two-pass SHADOW: A1 semantic extract, A2 category. Separate inference runs."""
    engine = CommercialRoutingV3Engine(crm_db=crm_db)
    registry, allowed, subs = engine.load_registry()
    title, okpd, okpd_name = _title_okpd(row)
    t0 = time.perf_counter()

    a1_prompt = build_a1_classify_prompt(title=title, okpd_code=okpd, okpd_name=okpd_name)
    a1 = run_shadow_inference(
        crm_db,
        procurement_id=procurement_id,
        procurement={"title": title, "okpd_code": okpd, "okpd_name": okpd_name},
        acquire_gpu=acquire_gpu,
        dry_run_persist=False,
        compute_business_preview=False,
        prompt_version=PROMPT_A1,
        prompt_text=a1_prompt,
    )
    a1_val = _load_model_json(crm_db, a1.get("inference_run_id"))

    form = str(a1_val.get("procurement_form") or "UNKNOWN")
    items = _list_str(a1_val.get("procured_items"))
    goods = _list_str(a1_val.get("explicit_goods"))
    if not items and a1_val.get("procured_item_summary"):
        items = [str(a1_val.get("procured_item_summary"))]
    evidence = _list_str(a1_val.get("evidence_phrases") or a1_val.get("evidence"))

    a2_prompt = build_a2_category_prompt(
        title=title,
        okpd_code=okpd,
        okpd_name=okpd_name,
        procurement_form=form,
        procured_items=items,
        explicit_goods=goods or items,
        registry=registry,
    )
    a2 = run_shadow_inference(
        crm_db,
        procurement_id=procurement_id,
        procurement={"title": title, "okpd_code": okpd, "okpd_name": okpd_name},
        allowed_categories=allowed,
        allowed_subcategories=subs,
        acquire_gpu=acquire_gpu,
        dry_run_persist=False,
        compute_business_preview=False,
        prompt_version=PROMPT_A2,
        prompt_text=a2_prompt,
    )
    a2_val = _load_model_json(crm_db, a2.get("inference_run_id"))
    elapsed = time.perf_counter() - t0
    cats = _cats(a2_val)
    invalid = [c for c in cats if c not in allowed]
    hyps = a2_val.get("commercial_category_hypotheses") or []
    object_spam = False
    if form != "DIRECT_GOODS_PURCHASE" and isinstance(hyps, list):
        # spam: product categories without confirmation_required on object/works
        productish = {"lighting", "computers", "flooring", "cable_support_systems", "furniture", "curbstone"}
        for h in hyps:
            if not isinstance(h, dict):
                continue
            code = str(h.get("category_code") or "")
            if code in productish and not h.get("confirmation_required"):
                object_spam = True
                break
        if len(cats) >= 3:
            object_spam = True

    return {
        "architecture": "A_TWO_PASS",
        "procurement_id": procurement_id,
        "A1_INFERENCE_RUN_ID": a1.get("inference_run_id"),
        "A2_INFERENCE_RUN_ID": a2.get("inference_run_id"),
        "A1_FORM": form,
        "A1_ITEMS": items,
        "A1_EXPLICIT_GOODS": goods,
        "A1_EVIDENCE": evidence,
        "A1_OBJECT_TYPE": a1_val.get("object_type"),
        "A1_OBJECT_SUBTYPE": a1_val.get("object_subtype"),
        "A1_WORK_STAGE": a1_val.get("work_stage"),
        "A1_EXTRACTION": a1_val,
        "A2_CATEGORY": cats,
        "A2_EMPTY_STATUS": a2_val.get("empty_hypothesis_status"),
        "A2_VALIDATED": a2_val,
        "A2_PROVENANCE": "MODEL_VALIDATED",
        "object_spam": object_spam,
        "invalid_category_codes": invalid,
        "seconds": round(elapsed, 3),
        "model_calls": 2,
        "production_assessment_mutated": False,
        "opportunities_mutated": False,
    }


def run_architecture_b(
    crm_db,
    *,
    procurement_id: int,
    row: Dict[str, Any],
    vocab=None,
    acquire_gpu: bool = True,
) -> Dict[str, Any]:
    """Extract with Qwen, map with deterministic registry vocabulary."""
    engine = CommercialRoutingV3Engine(crm_db=crm_db)
    registry, allowed, _ = engine.load_registry()
    if vocab is None:
        vocab = build_registry_vocabulary(crm_db, registry)
    title, okpd, okpd_name = _title_okpd(row)
    t0 = time.perf_counter()

    b_prompt = build_b_extract_prompt(title=title, okpd_code=okpd, okpd_name=okpd_name)
    b_run = run_shadow_inference(
        crm_db,
        procurement_id=procurement_id,
        procurement={"title": title, "okpd_code": okpd, "okpd_name": okpd_name},
        acquire_gpu=acquire_gpu,
        dry_run_persist=False,
        compute_business_preview=False,
        prompt_version=PROMPT_B_EXTRACT,
        prompt_text=b_prompt,
    )
    extraction = _load_model_json(crm_db, b_run.get("inference_run_id"))
    # normalize materials/evidence aliases for mapper
    if extraction.get("materials") and not extraction.get("material_families"):
        extraction = dict(extraction)
        extraction["material_families"] = extraction.get("materials")
    if extraction.get("evidence") and not extraction.get("explicit_product_evidence"):
        extraction = dict(extraction)
        extraction["explicit_product_evidence"] = extraction.get("evidence")

    mapped = map_extracted_to_categories(extraction, vocab, allowed=allowed)
    elapsed = time.perf_counter() - t0
    cats = _cats(mapped)
    invalid = [c for c in cats if c not in allowed]
    form = str(extraction.get("procurement_form") or "UNKNOWN")
    object_spam = bool(form != "DIRECT_GOODS_PURCHASE" and len(cats) >= 3)

    return {
        "architecture": "B_EXTRACT_MAP",
        "procurement_id": procurement_id,
        "B_INFERENCE_RUN_ID": b_run.get("inference_run_id"),
        "B_EXTRACTED_ITEM": extraction.get("procured_items") or [],
        "B_EXTRACTED_FORM": extraction.get("procurement_form"),
        "B_EXTRACTION": extraction,
        "B_MAPPED_CATEGORY": cats,
        "B_MAPPED_RESULT": mapped,
        "B_PROVENANCE": PROVENANCE,
        "registry_vocabulary_gaps": mapped.get("registry_vocabulary_gaps") or [],
        "object_spam": object_spam,
        "invalid_category_codes": invalid,
        "seconds": round(elapsed, 3),
        "model_calls": 1,
        "EXTRACT_MAP_IMPERSONATES_MODEL": False,
        "BUSINESS_MAPPING_IMPERSONATES_MODEL": False,
        "production_assessment_mutated": False,
        "opportunities_mutated": False,
    }


def _load_model_json(crm_db, run_id: Optional[int]) -> Dict[str, Any]:
    """Prefer RAW for architecture extract schemas; fall back to validated."""
    if not run_id:
        return {}
    rows = crm_db.execute_query(
        "SELECT raw_model_json, validated_model_result FROM crm_v3_model_inference_runs WHERE id=%s",
        (run_id,),
    )
    if not rows:
        return {}
    raw = rows[0].get("raw_model_json")
    val = rows[0].get("validated_model_result")
    if isinstance(raw, dict) and raw:
        out = dict(raw)
        if isinstance(val, dict) and val.get("commercial_category_hypotheses") is not None:
            out["commercial_category_hypotheses"] = val.get("commercial_category_hypotheses")
            if "empty_hypothesis_status" in val:
                out["empty_hypothesis_status"] = val.get("empty_hypothesis_status")
        return out
    return val if isinstance(val, dict) else {}
