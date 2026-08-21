"""Tests for T-lite SHADOW inference layer (CRM-V3-TLITE-BAKEOFF-1).

Verified invariants:
  - PRODUCTION_ASSESSMENTS_MUTATED=0  (shadow never writes to production tables)
  - run_kind=SHADOW only
  - RAW immutability guard blocks column overwrite
  - build_run_from_ollama correctly classifies model_call_failed / parse_failed /
    validated_success paths
  - capture_and_persist_inference_run: dry_run skips INSERT (returns id=None)
  - shadow_inference.run_shadow_inference: no crm_db writes except inference_runs table
  - validate_model_result: known-bad inputs return PARSED_SCHEMA_INVALID
  - prompt_v6_1 produces non-empty text  (smoke)
"""
from __future__ import annotations

from typing import Any, Dict, Set
from unittest.mock import MagicMock, patch

import pytest

from src.services.commercial_routing_v3.model_inference_runs import (
    RUN_KIND_SHADOW,
    InferenceRunRecord,
    assert_inference_run_immutable_update,
    build_run_from_ollama,
    capture_and_persist_inference_run,
    raw_model_sha256,
    validated_model_sha256,
)
from src.services.commercial_routing_v3.model_result_validator import (
    validate_model_result,
)
from src.domain.commercial_taxonomy import COMMERCIAL_KEEP_CODES


_ALLOWED_CATS: Set[str] = set(COMMERCIAL_KEEP_CODES)
_ALLOWED_SUBS: Dict[str, Set[str]] = {}

_VALID_RESULT: Dict[str, Any] = {
    "source_contour": "PUBLIC_44FZ",
    "procurement_form": "DIRECT_GOODS_PURCHASE",
    "analysis_modes": ["DIRECT_PRODUCT"],
    "object_context": [], "material_signals": [], "work_methods": [],
    "application_areas": [], "brands": [],
    "commercial_category_hypotheses": [{
        "category_code": "lighting",
        "subcategory_code": "SUBCATEGORY_NOT_ASSIGNED",
        "opportunity_track": "DIRECT_SUPPLY",
        "confidence": 0.8,
        "research_action": "LIGHT_RESEARCH",
        "reason_codes": ["title_product_match"],
        "evidence_role": "DIRECT_CATEGORY_EVIDENCE",
        "confirmation_required": False,
    }],
    "object_classification": {
        "object_sector": "SUPPLY", "object_type": "GOODS",
        "object_subtype": "LIGHTING", "object_context": [], "work_stage": "SUPPLY",
    },
    "document_research_priority": [],
    "empty_hypothesis_status": None, "preferred_opportunity_track": None,
    "empty_hypothesis_reason_codes": [], "discovery_required": False,
    "overall_research_action": "LIGHT_RESEARCH",
}

_VALID_NCE_RESULT: Dict[str, Any] = {
    "source_contour": "PUBLIC_44FZ",
    "procurement_form": "DIRECT_GOODS_PURCHASE",
    "analysis_modes": ["DIRECT_PRODUCT"],
    "object_context": [], "material_signals": [], "work_methods": [],
    "application_areas": [], "brands": [],
    "commercial_category_hypotheses": [],
    "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
    "empty_hypothesis_reason_codes": ["product_outside_registry"],
    "preferred_opportunity_track": None,
    "discovery_required": False, "overall_research_action": "SKIP",
}


def test_raw_sha256_stable() -> None:
    assert raw_model_sha256("hello") == raw_model_sha256("hello")
    assert len(raw_model_sha256("x")) == 64


def test_validated_sha256_key_order_invariant() -> None:
    h1 = validated_model_sha256({"a": 1, "b": [2, 3]})
    h2 = validated_model_sha256({"b": [2, 3], "a": 1})
    assert h1 == h2


def test_immutable_guard_blocks_raw() -> None:
    with pytest.raises(RuntimeError, match="MODEL_RAW_MUTATED_AFTER_INFERENCE"):
        assert_inference_run_immutable_update({"raw_model_text": "x"})


def test_immutable_guard_blocks_validated() -> None:
    with pytest.raises(RuntimeError, match="MODEL_RAW_MUTATED_AFTER_INFERENCE"):
        assert_inference_run_immutable_update({"validated_model_result": {}})


def test_immutable_guard_allows_mutable() -> None:
    assert_inference_run_immutable_update({"run_status": "COMPLETED"})


def test_build_run_model_call_failed() -> None:
    rec = build_run_from_ollama(
        procurement_id=42, run_kind=RUN_KIND_SHADOW, prompt="p",
        raw_text=None, parsed=None, parse_error=None,
        model_call_failed=True, ollama_metadata={}, retry_count=0,
        allowed_categories=_ALLOWED_CATS,
    )
    assert rec.parse_status == "MODEL_CALL_FAILED"
    assert rec.validation_status == "NOT_ATTEMPTED"
    assert rec.validated_model_result is None


def test_build_run_parse_failed() -> None:
    rec = build_run_from_ollama(
        procurement_id=99, run_kind=RUN_KIND_SHADOW, prompt="p",
        raw_text='{"bad"', parsed=None, parse_error="json_parse_error",
        model_call_failed=False, ollama_metadata={}, retry_count=1,
        allowed_categories=_ALLOWED_CATS,
    )
    assert rec.parse_status == "RAW_RECEIVED_PARSE_FAILED"
    assert rec.raw_model_sha256 is not None
    assert "json_parse_error" in rec.validation_errors


def test_build_run_validated_success() -> None:
    import json
    rec = build_run_from_ollama(
        procurement_id=23, run_kind=RUN_KIND_SHADOW, prompt="p",
        raw_text=json.dumps(_VALID_RESULT), parsed=dict(_VALID_RESULT),
        parse_error=None, model_call_failed=False,
        ollama_metadata={"model": "hf.co/t-tech/T-lite-it-2.1-GGUF:Q4_K_M"},
        retry_count=0, allowed_categories=_ALLOWED_CATS,
    )
    assert rec.validation_status == "VALIDATED_SUCCESS"
    assert rec.validated_model_result is not None
    assert rec.model_name == "hf.co/t-tech/T-lite-it-2.1-GGUF:Q4_K_M"


def test_build_run_nce_success() -> None:
    import json
    rec = build_run_from_ollama(
        procurement_id=999, run_kind=RUN_KIND_SHADOW, prompt="p",
        raw_text=json.dumps(_VALID_NCE_RESULT), parsed=dict(_VALID_NCE_RESULT),
        parse_error=None, model_call_failed=False,
        ollama_metadata={}, retry_count=0, allowed_categories=_ALLOWED_CATS,
    )
    assert rec.validation_status == "VALIDATED_SUCCESS"
    val = rec.validated_model_result
    assert isinstance(val, dict)
    assert val.get("empty_hypothesis_status") == "NO_COMMERCIAL_ENTRY"
    assert val.get("commercial_category_hypotheses") == []


def test_capture_persist_dry_run_no_insert() -> None:
    import json
    crm_db = MagicMock()
    crm_db.execute_scalar.return_value = True
    rec = capture_and_persist_inference_run(
        crm_db, procurement_id=1, run_kind=RUN_KIND_SHADOW, prompt="p",
        raw_text=json.dumps(_VALID_RESULT), parsed=dict(_VALID_RESULT),
        allowed_categories=_ALLOWED_CATS, dry_run=True,
    )
    assert rec.id is None
    crm_db.execute_query.assert_not_called()


def test_capture_persist_non_dry_run_inserts() -> None:
    import json
    crm_db = MagicMock()
    crm_db.execute_scalar.return_value = True
    crm_db.execute_query.return_value = [{"id": 77}]
    rec = capture_and_persist_inference_run(
        crm_db, procurement_id=23, run_kind=RUN_KIND_SHADOW, prompt="p",
        raw_text=json.dumps(_VALID_RESULT), parsed=dict(_VALID_RESULT),
        allowed_categories=_ALLOWED_CATS, dry_run=False,
    )
    assert rec.id == 77
    crm_db.execute_query.assert_called_once()


def test_validate_result_success() -> None:
    r = validate_model_result(dict(_VALID_RESULT), allowed_categories=_ALLOWED_CATS, allowed_subcategories=_ALLOWED_SUBS)
    assert r.status == "VALIDATED_SUCCESS"


def test_validate_result_rejects_non_dict() -> None:
    r = validate_model_result("not a dict", allowed_categories=_ALLOWED_CATS, allowed_subcategories=_ALLOWED_SUBS)  # type: ignore
    assert r.status == "PARSED_SCHEMA_INVALID"


def test_validate_result_strips_invalid_category() -> None:
    bad = dict(_VALID_RESULT)
    bad["commercial_category_hypotheses"] = [
        {"category_code": "NOT_REAL_xyz", "opportunity_track": "DIRECT_SUPPLY", "confidence": 0.9}
    ]
    r = validate_model_result(bad, allowed_categories=_ALLOWED_CATS, allowed_subcategories=_ALLOWED_SUBS)
    assert r.status == "VALIDATED_SUCCESS"
    cats = [h.get("category_code") for h in (r.validated or {}).get("commercial_category_hypotheses", [])]
    assert "NOT_REAL_xyz" not in cats


def test_validate_no_medal_invention() -> None:
    r = validate_model_result(dict(_VALID_RESULT), allowed_categories=_ALLOWED_CATS, allowed_subcategories=_ALLOWED_SUBS)
    assert r.status == "VALIDATED_SUCCESS"
    for h in (r.validated or {}).get("commercial_category_hypotheses", []):
        assert h.get("candidate_medal") is None
        assert h.get("candidate_score") is None
        assert h.get("commercial_priority_score") is None


def test_shadow_inference_no_production_mutation() -> None:
    import json
    from src.services.commercial_routing_v3.shadow_inference import run_shadow_inference

    class _Bundle:
        raw_text = json.dumps(_VALID_RESULT)
        parsed = dict(_VALID_RESULT)
        meta = {"model": "hf.co/t-tech/T-lite-it-2.1-GGUF:Q4_K_M"}
        retry_count = 0

    def _db_query(sql, *args, **kwargs):
        # Subcategory join SELECT returns [] (no subcats in test).
        # INSERT RETURNING id returns the run row.
        if "INSERT" in str(sql).upper():
            return [{"id": 123}]
        return []

    crm_db = MagicMock()
    crm_db.execute_scalar.return_value = True
    crm_db.execute_query.side_effect = _db_query

    # load_active_commercial_categories is called by engine.load_registry() when crm_db is set.
    _fake_cats = [
        {"category_code": c, "category_name": c, "lifecycle_state": "ACTIVE"}
        for c in sorted(_ALLOWED_CATS)
    ]
    with patch("src.services.commercial_routing_v3.shadow_inference.call_ollama_qwen_bundle", return_value=_Bundle()), \
         patch("src.services.commercial_routing_v3.engine.load_active_commercial_categories", return_value=_fake_cats):
        out = run_shadow_inference(
            crm_db, procurement_id=42,
            procurement={"title": "Test", "okpd_code": "27.40", "price": 100000.0, "source_table": "eis_44fz"},
            acquire_gpu=False, dry_run_persist=False, compute_business_preview=False,
            prompt_version="v3_category_centric_routing_7b_v6_1", prompt_text="p",
            experiment_model="hf.co/t-tech/T-lite-it-2.1-GGUF:Q4_K_M",
        )

    assert out["production_assessment_mutated"] is False
    assert out["opportunities_mutated"] is False
    assert out["visibility_mutated"] is False
    assert out["run_kind"] == RUN_KIND_SHADOW


def test_shadow_inference_failure_does_not_raise() -> None:
    from src.services.commercial_routing_v3.shadow_inference import run_shadow_inference

    def _db_query(sql, *args, **kwargs):
        if "INSERT" in str(sql).upper():
            return [{"id": 555}]
        return []

    crm_db = MagicMock()
    crm_db.execute_scalar.return_value = True
    crm_db.execute_query.side_effect = _db_query

    _fake_cats = [
        {"category_code": c, "category_name": c, "lifecycle_state": "ACTIVE"}
        for c in sorted(_ALLOWED_CATS)
    ]
    with patch("src.services.commercial_routing_v3.shadow_inference.call_ollama_qwen_bundle", return_value=None), \
         patch("src.services.commercial_routing_v3.engine.load_active_commercial_categories", return_value=_fake_cats):
        out = run_shadow_inference(
            crm_db, procurement_id=99,
            procurement={"title": "Test", "price": 0.0, "source_table": "eis_44fz"},
            acquire_gpu=False, dry_run_persist=False, compute_business_preview=False,
            prompt_text="p", experiment_model="hf.co/t-tech/T-lite-it-2.1-GGUF:Q4_K_M",
        )
    assert out["parse_status"] == "MODEL_CALL_FAILED"
    assert out["production_assessment_mutated"] is False



def test_production_model_still_qwen25_7b() -> None:
    from src.services.commercial_routing_v3.prompt import PROMPT_VERSION as PROD_PV
    assert PROD_PV == "v3_category_centric_routing_7b_v5", (
        f"Production PROMPT_VERSION changed: {PROD_PV!r}"
    )


def test_production_and_v61_prompt_versions_distinct() -> None:
    from src.services.commercial_routing_v3.prompt import PROMPT_VERSION as PROD
    from src.services.commercial_routing_v3.prompt_v6_1 import PROMPT_VERSION as V61
    assert PROD == "v3_category_centric_routing_7b_v5"
    assert V61 == "v3_category_centric_routing_7b_v6_1"
    assert PROD != V61


def test_build_v6_1_prompt_non_empty() -> None:
    from src.services.commercial_routing_v3.prompt_v6_1 import build_v6_1_prompt
    procurement = {
        "title": "Поставка светодиодных светильников",
        "okpd_code": "27.40", "price": 500000.0,
        "source_table": "eis_44fz", "law_type": "44FZ",
        "customer": "МКУ", "region": "Московская область",
    }
    registry = [{"category_code": "lighting", "category_name": "Осветительное оборудование",
                  "lifecycle_state": "ACTIVE", "subcategories": []}]
    prompt = build_v6_1_prompt(procurement, registry=registry, okpd_priors=[],
                                routing_signals=[], procurement_form_prior="DIRECT_GOODS_PURCHASE")
    assert isinstance(prompt, str) and len(prompt) > 200
    assert "lighting" in prompt


def test_run_shadow_batch_zero_production_mutations() -> None:
    from src.services.commercial_routing_v3.shadow_inference import run_shadow_batch
    crm_db = MagicMock()
    shadow_return = {
        "procurement_id": 1, "inference_run_id": 1, "run_kind": RUN_KIND_SHADOW,
        "parse_status": "PARSED_OK", "validation_status": "VALIDATED_SUCCESS",
        "raw_model_sha256": "a", "validated_model_sha256": "b",
        "validation_errors": [], "business_preview": None,
        "production_assessment_mutated": False,
        "opportunities_mutated": False, "visibility_mutated": False,
        "run": MagicMock(id=1),
    }
    with patch("src.services.commercial_routing_v3.shadow_inference.run_shadow_inference", return_value=shadow_return):
        result = run_shadow_batch(crm_db, [
            {"procurement_id": 23, "procurement": {"title": "A"}},
            {"procurement_id": 41, "procurement": {"title": "B"}},
        ])
    assert result["production_assessments_mutated"] == 0
    assert result["opportunities_mutated"] == 0
    assert result["count"] == 2
