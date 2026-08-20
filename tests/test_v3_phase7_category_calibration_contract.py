"""Phase 7 — v6 category contract + calibration invariants (no live Ollama)."""
from __future__ import annotations

from copy import deepcopy

import pytest

from src.services.commercial_routing_v3.model_result_validator import validate_model_result
from src.services.commercial_routing_v3.prompt import (
    PROMPT_VERSION as V5,
    allowed_category_codes_block,
    build_v3_prompt_from_model_input,
)
from src.services.commercial_routing_v3.prompt_v6 import (
    PROMPT_VERSION as V6,
    build_v6_prompt,
    build_v6_prompt_from_model_input,
)
from src.services.commercial_routing_v3.shadow_inference import run_shadow_inference


_REGISTRY = [
    {
        "category_code": "lighting",
        "category_name": "Освещение",
        "lifecycle_state": "ACTIVE",
        "subcategories": [],
    },
    {
        "category_code": "computers",
        "category_name": "Компьютеры",
        "lifecycle_state": "ACTIVE",
        "subcategories": [],
    },
    {
        "category_code": "drainage_water_management",
        "category_name": "Дренаж",
        "lifecycle_state": "ACTIVE",
        "subcategories": [],
    },
]

_ALLOWED = {c["category_code"] for c in _REGISTRY}


def _mi(title: str, okpd: str = "27.40.00", okpd_name: str = "Светильники") -> dict:
    return {
        "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
        "title": title,
        "okpd_codes": [okpd] if okpd else [],
        "okpd_name": okpd_name,
        "price": 100000,
        "customer": "TEST",
        "law_type": "44-FZ",
        "source_table": "open",
        "region": "Test",
    }


def test_prompt_v6_distinct_from_v5() -> None:
    assert V5 == "v3_category_centric_routing_7b_v5"
    assert V6.startswith("v3_category_centric_routing_7b_v6")
    assert V6 != V5
    assert V6 == "v3_category_centric_routing_7b_v6_1"

def test_v6_registry_present_and_exact_codes() -> None:
    text = build_v6_prompt_from_model_input(
        _mi("Поставка светильников"),
        registry=_REGISTRY,
        okpd_priors=[],
        procurement_form_prior="DIRECT_GOODS_PURCHASE",
    )
    assert "ALLOWED_COMMERCIAL_CATEGORY_CODES" in text
    assert "- lighting" in text
    assert "- computers" in text
    block = allowed_category_codes_block(_REGISTRY)
    assert "lighting" in block and "computers" in block


def test_v6_direct_clear_positive_contract() -> None:
    text = build_v6_prompt_from_model_input(
        _mi("Поставка светодиодных светильников"),
        registry=_REGISTRY,
        okpd_priors=[],
        procurement_form_prior="DIRECT_GOODS_PURCHASE",
    )
    assert "DIRECT_GOODS_PURCHASE" in text
    assert "POSITIVE EXAMPLE lighting" in text
    assert '"category_code":"lighting"' in text
    assert "светильник/лампа→lighting" in text


def test_v6_direct_outside_registry_contract() -> None:
    text = build_v6_prompt_from_model_input(
        _mi("Поставка газовых счетчиков", okpd="26.51", okpd_name="Счетчики газа"),
        registry=_REGISTRY,
        okpd_priors=[],
        procurement_form_prior="DIRECT_GOODS_PURCHASE",
    )
    assert "NO_COMMERCIAL_ENTRY" in text
    assert "NEGATIVE EXAMPLE" in text
    assert "product_outside_registry" in text


def test_v6_object_contextual_contract() -> None:
    text = build_v6_prompt_from_model_input(
        _mi("Капитальный ремонт автомобильной дороги", okpd="42.11", okpd_name="Дороги"),
        registry=_REGISTRY,
        okpd_priors=[],
        procurement_form_prior="CONSTRUCTION_WORKS",
    )
    assert "confirmation_required=true" in text or '"confirmation_required":true' in text
    assert "Do NOT invent drainage/waterproofing/lighting merely because" in text
    assert "OBJECT EXAMPLE" in text


def test_v6_empty_status_mandatory_when_no_hypotheses() -> None:
    text = build_v6_prompt_from_model_input(
        _mi("Поставка"),
        registry=_REGISTRY,
        okpd_priors=[],
        procurement_form_prior="UNKNOWN",
    )
    assert "empty_hypothesis_status MUST be one of" in text or (
        "empty hypotheses without empty_hypothesis_status is invalid" in text
    )

def test_python_prior_does_not_mutate_result() -> None:
    """Priors are prompt context only; validator must not inject prior categories."""
    raw = {
        "source_contour": "PUBLIC_44FZ",
        "procurement_form": "DIRECT_GOODS_PURCHASE",
        "commercial_category_hypotheses": [],
        "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
        "overall_research_action": "SKIP",
    }
    priors = [{"commercial_category_code": "lighting", "okpd_pattern": "27.40"}]
    vr = validate_model_result(
        deepcopy(raw),
        allowed_categories=_ALLOWED,
        allowed_subcategories={},
    )
    assert vr.validated is not None
    assert vr.validated["commercial_category_hypotheses"] == []
    del priors
    assert vr.validated.get("empty_hypothesis_status") == "NO_COMMERCIAL_ENTRY"


def test_validator_does_not_create_categories() -> None:
    vr = validate_model_result(
        {
            "commercial_category_hypotheses": [],
            "empty_hypothesis_status": "INSUFFICIENT_EVIDENCE",
        },
        allowed_categories=_ALLOWED,
        allowed_subcategories={},
    )
    assert vr.validated is not None
    assert vr.validated["commercial_category_hypotheses"] == []


def test_invalid_category_code_rejected() -> None:
    vr = validate_model_result(
        {
            "commercial_category_hypotheses": [
                {
                    "category_code": "not_a_real_category",
                    "opportunity_track": "DIRECT_SUPPLY",
                    "confidence": 0.9,
                }
            ]
        },
        allowed_categories=_ALLOWED,
        allowed_subcategories={},
    )
    assert vr.validated is not None
    assert vr.validated["commercial_category_hypotheses"] == []
    assert any("rejected_category_not_in_registry" in e for e in vr.errors)


def test_zero_confidence_preserved() -> None:
    vr = validate_model_result(
        {
            "commercial_category_hypotheses": [
                {
                    "category_code": "lighting",
                    "opportunity_track": "DIRECT_SUPPLY",
                    "confidence": 0.0,
                }
            ]
        },
        allowed_categories=_ALLOWED,
        allowed_subcategories={},
    )
    assert vr.validated is not None
    assert len(vr.validated["commercial_category_hypotheses"]) == 1
    assert vr.validated["commercial_category_hypotheses"][0]["confidence"] == 0.0

def test_v6_build_via_procurement_wrapper() -> None:
    text = build_v6_prompt(
        {"v3_model_input": _mi("Поставка ноутбуков"), "title": "Поставка ноутбуков"},
        registry=_REGISTRY,
        okpd_priors=[],
        routing_signals=[],
        procurement_form_prior="DIRECT_GOODS_PURCHASE",
    )
    assert V6 in text
    assert "computers" in allowed_category_codes_block(_REGISTRY)


def test_shadow_override_does_not_call_assessment_write(monkeypatch) -> None:
    """SHADOW with prompt override must not write assessments/opportunities."""

    class _Crm:
        writes = []

        def execute_query(self, *a, **k):
            return []

        def execute_update(self, *a, **k):
            self.writes.append(a[0] if a else "")
            return 0

        def execute_scalar(self, *a, **k):
            return 0

    class _Engine:
        def __init__(self, crm_db=None):
            self.crm_db = crm_db

        def load_registry(self):
            return _REGISTRY, _ALLOWED, {}

        def build_prompt_context(self, procurement):
            raise AssertionError("should use prompt_text override")

    monkeypatch.setattr(
        "src.services.commercial_routing_v3.shadow_inference.CommercialRoutingV3Engine",
        _Engine,
    )

    def _fake_bundle(*a, **k):
        class B:
            raw_text = '{"commercial_category_hypotheses":[],"empty_hypothesis_status":"NO_COMMERCIAL_ENTRY","overall_research_action":"SKIP"}'
            parsed = {
                "commercial_category_hypotheses": [],
                "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
                "overall_research_action": "SKIP",
            }
            meta = {"model": "qwen2.5:7b"}
            retry_count = 0

        return B()

    monkeypatch.setattr(
        "src.services.commercial_routing_v3.shadow_inference.call_ollama_qwen_bundle",
        _fake_bundle,
    )

    def _capture(*a, **k):
        from types import SimpleNamespace

        return SimpleNamespace(
            id=1,
            parse_status="PARSED",
            validation_status="VALIDATED_SUCCESS",
            validated_model_result={
                "commercial_category_hypotheses": [],
                "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
            },
            raw_model_json={
                "commercial_category_hypotheses": [],
                "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
            },
            raw_model_sha256="abc",
            validated_model_sha256="def",
            validation_errors=[],
            prompt_version=k.get("prompt_version"),
        )

    monkeypatch.setattr(
        "src.services.commercial_routing_v3.shadow_inference.capture_and_persist_inference_run",
        _capture,
    )

    out = run_shadow_inference(
        _Crm(),
        procurement_id=1,
        procurement={"title": "x"},
        prompt_version=V6,
        prompt_text="dummy prompt with lighting computers",
        compute_business_preview=False,
        dry_run_persist=True,
        acquire_gpu=False,
    )
    assert out["production_assessment_mutated"] is False
    assert out["opportunities_mutated"] is False
    assert out["visibility_mutated"] is False
    assert not any("procurement_ai_assessments" in str(w) for w in _Crm.writes)
    assert not any("crm_procurement_category_opportunities" in str(w) for w in _Crm.writes)

def test_v5_prompt_still_unchanged_default() -> None:
    text = build_v3_prompt_from_model_input(
        _mi("Поставка светильников"),
        registry=_REGISTRY,
        okpd_priors=[],
        procurement_form_prior="DIRECT_GOODS_PURCHASE",
    )
    assert V5 in text
    assert V6 not in text
