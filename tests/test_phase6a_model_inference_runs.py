"""Phase 6A — immutable model inference storage structural tests."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

import pytest

from src.services.ai_assessment_runner import OllamaInferenceBundle, call_ollama_qwen
from src.services.commercial_routing_v3.model_inference_runs import (
    RUN_KIND_PRODUCTION,
    RUN_KIND_SHADOW,
    InferenceRunRecord,
    assert_inference_run_immutable_update,
    build_run_from_ollama,
    capture_and_persist_inference_run,
    raw_model_sha256,
    validated_model_sha256,
)
from src.services.commercial_routing_v3.model_result_validator import validate_model_result
from src.services.commercial_routing_v3.shadow_inference import run_shadow_inference


ALLOWED = {"lighting", "computers", "waterproofing", "drainage_water_management"}


class _FakeDb:
    """Minimal CRM db stub capturing INSERTs and refusing opportunity writes."""

    def __init__(self) -> None:
        self.inserts: List[Dict[str, Any]] = []
        self.updates: List[str] = []
        self._next_id = 1
        self.table_ready = True

    def execute_scalar(self, sql: str, params=None):
        if "crm_v3_model_inference_runs" in sql:
            return self.table_ready
        return None

    def execute_query(self, sql: str, params=None):
        if "INSERT INTO crm_v3_model_inference_runs" in sql:
            rid = self._next_id
            self._next_id += 1
            self.inserts.append({"sql": sql, "params": params, "id": rid})
            return [{"id": rid}]
        return []

    def execute_update(self, sql: str, params=None):
        self.updates.append(sql)
        if "crm_procurement_category_opportunities" in sql:
            raise AssertionError("shadow/opportunities must not be mutated")
        if "procurement_ai_assessments" in sql:
            raise AssertionError("shadow must not mutate production assessments")
        return 0


def _valid_parsed(**over) -> Dict[str, Any]:
    row = {
        "source_contour": "PUBLIC_44FZ",
        "procurement_form": "DIRECT_GOODS_PURCHASE",
        "analysis_modes": ["DIRECT_PRODUCT"],
        "object_context": [],
        "material_signals": [],
        "work_methods": [],
        "application_areas": [],
        "brands": [],
        "commercial_category_hypotheses": [
            {
                "category_code": "lighting",
                "opportunity_track": "DIRECT_SUPPLY",
                "confidence": 0.0,
                "research_action": "LIGHT_RESEARCH",
                "reason_codes": ["okpd_match"],
            }
        ],
        "empty_hypothesis_status": None,
        "preferred_opportunity_track": None,
        "empty_hypothesis_reason_codes": [],
        "discovery_required": False,
        "overall_research_action": "LIGHT_RESEARCH",
    }
    row.update(over)
    return row


def test_raw_hash_is_exact_utf8_text_hash() -> None:
    raw = '{"procurement_form":"DIRECT_GOODS_PURCHASE"}'
    assert raw_model_sha256(raw) == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    # Must NOT equal hash of pretty/parsed representation.
    pretty = json.dumps(json.loads(raw), indent=2, sort_keys=True)
    assert raw_model_sha256(raw) != raw_model_sha256(pretty)


def test_validated_hash_deterministic() -> None:
    a = {"b": 1, "a": [2, 3]}
    b = {"a": [2, 3], "b": 1}
    assert validated_model_sha256(a) == validated_model_sha256(b)


def test_telemetry_not_in_model_json_via_call_wrapper(monkeypatch) -> None:
    from src.services import ai_assessment_runner as ar

    def _fake_bundle(*_a, **_k):
        return OllamaInferenceBundle(
            parsed={"procurement_form": "UNKNOWN", "_should_not": 1},
            raw_text='{"procurement_form":"UNKNOWN"}',
            meta={"model": "qwen2.5:7b"},
            retry_count=0,
        )

    monkeypatch.setattr(ar, "call_ollama_qwen_bundle", _fake_bundle)
    out = call_ollama_qwen("{}")
    assert out is not None
    assert "_ollama_meta" not in out
    assert "_model_format_retry_count" not in out
    assert "_should_not" not in out


def test_validator_does_not_add_category_scope_confidence_score_medal() -> None:
    parsed = {
        "procurement_form": "CONSTRUCTION_WORKS",
        "analysis_modes": ["EMBEDDED_MATERIAL_DISCOVERY"],
        "commercial_category_hypotheses": [],
        "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
        "overall_research_action": "SKIP",
        "business_scope_status": "IN_PROFILE",  # must be rejected, not invented
        "candidate_score": 88,
        "candidate_medal": "GOLD",
    }
    vr = validate_model_result(parsed, allowed_categories=ALLOWED)
    assert vr.status == "VALIDATED_SUCCESS"
    assert vr.validated is not None
    assert vr.validated["commercial_category_hypotheses"] == []
    assert "business_scope_status" not in vr.validated
    assert "candidate_score" not in vr.validated
    assert "candidate_medal" not in vr.validated
    # No invented hypothesis / confidence.
    assert not any(e.startswith("invent") for e in vr.errors)


def test_validator_preserves_zero_confidence_and_does_not_invent_missing() -> None:
    parsed = _valid_parsed()
    parsed["commercial_category_hypotheses"][0]["confidence"] = 0.0
    vr = validate_model_result(parsed, allowed_categories=ALLOWED)
    assert vr.validated["commercial_category_hypotheses"][0]["confidence"] == 0.0

    parsed2 = _valid_parsed()
    parsed2["commercial_category_hypotheses"][0].pop("confidence", None)
    parsed2["commercial_category_hypotheses"][0].pop("category_confidence", None)
    vr2 = validate_model_result(parsed2, allowed_categories=ALLOWED)
    assert vr2.validated["commercial_category_hypotheses"][0]["confidence"] is None


def test_build_run_persists_raw_before_enrichment_semantics() -> None:
    raw = json.dumps(_valid_parsed(), ensure_ascii=False)
    rec = build_run_from_ollama(
        procurement_id=101,
        run_kind=RUN_KIND_PRODUCTION,
        prompt="prompt-text",
        raw_text=raw,
        parsed=_valid_parsed(),
        parse_error=None,
        model_call_failed=False,
        ollama_metadata={"model": "qwen2.5:7b", "raw_text": raw},
        retry_count=1,
        allowed_categories=ALLOWED,
    )
    assert rec.parse_status == "PARSED_OK"
    assert rec.validation_status == "VALIDATED_SUCCESS"
    assert rec.raw_model_text == raw
    assert rec.raw_model_sha256 == raw_model_sha256(raw)
    assert rec.validated_model_result is not None
    assert rec.validated_model_sha256 == validated_model_sha256(rec.validated_model_result)
    # Telemetry keys must not appear in validated model namespace.
    assert "_ollama_meta" not in (rec.raw_model_json or {})
    assert "_ollama_meta" not in (rec.validated_model_result or {})


def test_parse_failure_preserves_raw() -> None:
    raw = "NOT JSON {{{"
    rec = build_run_from_ollama(
        procurement_id=102,
        run_kind=RUN_KIND_PRODUCTION,
        prompt="p",
        raw_text=raw,
        parsed=None,
        parse_error="parse_failed",
        model_call_failed=False,
        ollama_metadata={"model": "qwen2.5:7b"},
        retry_count=2,
        allowed_categories=ALLOWED,
    )
    assert rec.parse_status == "RAW_RECEIVED_PARSE_FAILED"
    assert rec.raw_model_text == raw
    assert rec.raw_model_sha256 == raw_model_sha256(raw)
    assert rec.validated_model_result is None


def test_validation_failure_preserves_raw() -> None:
    # Non-object hypotheses list → schema invalid, raw still kept.
    raw = '{"commercial_category_hypotheses":"bad"}'
    rec = build_run_from_ollama(
        procurement_id=103,
        run_kind=RUN_KIND_PRODUCTION,
        prompt="p",
        raw_text=raw,
        parsed={"commercial_category_hypotheses": "bad"},
        parse_error=None,
        model_call_failed=False,
        ollama_metadata={},
        retry_count=0,
        allowed_categories=ALLOWED,
    )
    assert rec.raw_model_text == raw
    assert rec.raw_model_sha256 == raw_model_sha256(raw)
    assert rec.validation_status == "PARSED_SCHEMA_INVALID"


def test_reassessment_creates_second_run_first_unchanged() -> None:
    db = _FakeDb()
    raw1 = json.dumps(_valid_parsed(), ensure_ascii=False)
    r1 = capture_and_persist_inference_run(
        db,
        procurement_id=200,
        run_kind=RUN_KIND_PRODUCTION,
        prompt="p1",
        raw_text=raw1,
        parsed=_valid_parsed(),
        allowed_categories=ALLOWED,
    )
    raw2 = json.dumps(_valid_parsed(procurement_form="CONSTRUCTION_WORKS"), ensure_ascii=False)
    r2 = capture_and_persist_inference_run(
        db,
        procurement_id=200,
        run_kind=RUN_KIND_PRODUCTION,
        prompt="p2",
        raw_text=raw2,
        parsed=_valid_parsed(procurement_form="CONSTRUCTION_WORKS"),
        allowed_categories=ALLOWED,
    )
    assert r1.id != r2.id
    assert len(db.inserts) == 2
    assert db.inserts[0]["params"][7] == raw1  # raw_model_text positional
    assert db.inserts[1]["params"][7] == raw2
    # Application immutability guard.
    with pytest.raises(RuntimeError):
        assert_inference_run_immutable_update({"raw_model_text": "mutated"})


def test_object_routing_only_after_validated_snapshot(monkeypatch) -> None:
    """route_with_ai must receive validated snapshot, not mutate the frozen run."""
    calls: List[Dict[str, Any]] = []

    class _Eng:
        def load_registry(self):
            return [], ALLOWED, {}

        def build_prompt_context(self, procurement):
            return "PROMPT"

        def route_with_ai(self, procurement, ai_raw, **_k):
            calls.append(dict(ai_raw))
            class _D:
                routing_version = "v3"
                commercial_category_hypotheses = []
                empty_hypothesis_status = None
                overall_research_action = "SKIP"
            return _D()

    from src.services.commercial_routing_v3 import shadow_inference as si

    monkeypatch.setattr(si, "CommercialRoutingV3Engine", lambda crm_db=None: _Eng())

    def _bundle(*_a, **_k):
        return OllamaInferenceBundle(
            parsed=_valid_parsed(),
            raw_text=json.dumps(_valid_parsed()),
            meta={"model": "qwen2.5:7b"},
            retry_count=0,
        )

    monkeypatch.setattr(si, "call_ollama_qwen_bundle", _bundle)

    db = _FakeDb()
    out = run_shadow_inference(
        db,
        procurement_id=55,
        procurement={"title": "светильники", "okpd_code": "27.40"},
        acquire_gpu=False,
        dry_run_persist=False,
        compute_business_preview=True,
    )
    assert out["production_assessment_mutated"] is False
    assert out["opportunities_mutated"] is False
    assert out["visibility_mutated"] is False
    assert out["inference_run_id"] == 1
    assert out["raw_model_sha256"]
    assert calls, "business preview should call route_with_ai after validated snapshot"
    assert "_ollama_meta" not in calls[0]
    assert calls[0].get("commercial_category_hypotheses")


def test_shadow_does_not_create_production_assessment(monkeypatch) -> None:
    from src.services.commercial_routing_v3 import shadow_inference as si

    class _Eng:
        def load_registry(self):
            return [], ALLOWED, {}

        def build_prompt_context(self, procurement):
            return "PROMPT"

        def route_with_ai(self, *a, **k):
            raise AssertionError("preview disabled")

    monkeypatch.setattr(si, "CommercialRoutingV3Engine", lambda crm_db=None: _Eng())
    monkeypatch.setattr(
        si,
        "call_ollama_qwen_bundle",
        lambda *a, **k: OllamaInferenceBundle(
            parsed=_valid_parsed(),
            raw_text=json.dumps(_valid_parsed()),
            meta={"model": "qwen2.5:7b"},
            retry_count=0,
        ),
    )
    db = _FakeDb()
    out = run_shadow_inference(
        db,
        procurement_id=77,
        procurement={"title": "x"},
        acquire_gpu=False,
        compute_business_preview=False,
    )
    assert out["production_assessment_mutated"] is False
    assert not any("procurement_ai_assessments" in u for u in db.updates)
    assert len(db.inserts) == 1
    assert db.inserts[0]["params"][1] == RUN_KIND_SHADOW


def test_historical_null_inference_run_id_readable() -> None:
    # Effective assessment path still works without inference_run_id.
    from src.services.effective_assessment import _compute_effective_assessment

    ea = _compute_effective_assessment(
        1,
        {
            "status": "SUCCESS",
            "normalized_result": {
                "business_scope_status": "IN_PROFILE",
                "category_opportunities": [],
            },
            "confidence": 0.0,
        },
        None,
        [],
    )
    assert ea.ai_status == "ASSESSED"
    assert ea.confidence == 0.0
