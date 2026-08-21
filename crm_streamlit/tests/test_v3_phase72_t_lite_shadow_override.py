"""Phase 7.2 — SHADOW experiment_model override contract (no live Ollama)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.services.commercial_routing_v3.model_inference_runs import InferenceRunRecord
from src.services.commercial_routing_v3.shadow_inference import run_shadow_inference


class _Crm:
    writes: list = []

    def execute_query(self, sql: str, params=None):
        return []

    def execute_scalar(self, sql: str, params=None):
        return 0


def test_shadow_passes_experiment_model_to_bundle(monkeypatch) -> None:
    captured: Dict[str, Any] = {}

    class _Bundle:
        raw_text = '{"procurement_form":"SUPPLY","commercial_category_hypotheses":[]}'
        parsed = {"procurement_form": "SUPPLY", "commercial_category_hypotheses": []}
        meta = {"model": "hf.co/t-tech/T-lite-it-2.1-GGUF:Q4_K_M", "request_model": "hf.co/t-tech/T-lite-it-2.1-GGUF:Q4_K_M"}
        retry_count = 0

    def _bundle(prompt, **kwargs):
        captured.update(kwargs)
        return _Bundle()

    def _capture(crm, **kwargs):
        captured["persist_model_name"] = kwargs.get("model_name")
        captured["run_kind"] = kwargs.get("run_kind")
        return InferenceRunRecord(
            id=991,
            procurement_id=kwargs["procurement_id"],
            run_kind=kwargs["run_kind"],
            parse_status="PARSED_OK",
            validation_status="VALIDATED_SUCCESS",
            raw_model_json=kwargs.get("parsed") or {},
            validated_model_result=kwargs.get("parsed") or {},
            raw_model_sha256="sha-raw",
            validated_model_sha256="sha-val",
            validation_errors=[],
            prompt_version=kwargs.get("prompt_version"),
            model_name=kwargs.get("model_name"),
        )

    class _Engine:
        def load_registry(self):
            return [], set(), {}

        def build_prompt_context(self, procurement):
            return "unused"

    monkeypatch.setattr(
        "src.services.commercial_routing_v3.shadow_inference.call_ollama_qwen_bundle",
        _bundle,
    )
    monkeypatch.setattr(
        "src.services.commercial_routing_v3.shadow_inference.capture_and_persist_inference_run",
        _capture,
    )
    monkeypatch.setattr(
        "src.services.commercial_routing_v3.shadow_inference.CommercialRoutingV3Engine",
        lambda crm_db=None: _Engine(),
    )

    out = run_shadow_inference(
        _Crm(),
        procurement_id=42,
        procurement={"title": "Поставка моноблоков"},
        prompt_version="v3_category_centric_routing_7b_v6_1",
        prompt_text="frozen-v61-prompt",
        experiment_model="hf.co/t-tech/T-lite-it-2.1-GGUF:Q4_K_M",
        num_predict=640,
        format_json=False,
        compute_business_preview=False,
        dry_run_persist=True,
        acquire_gpu=False,
    )
    assert captured.get("experiment_model") == "hf.co/t-tech/T-lite-it-2.1-GGUF:Q4_K_M"
    assert captured.get("num_predict") == 640
    assert captured.get("format_json") is False
    assert captured.get("persist_model_name") == "hf.co/t-tech/T-lite-it-2.1-GGUF:Q4_K_M"
    assert captured.get("run_kind") == "SHADOW"
    assert out["production_assessment_mutated"] is False
    assert out["raw_model_sha256"] == "sha-raw"


def test_shadow_default_keeps_production_model_path(monkeypatch) -> None:
    captured: Dict[str, Any] = {}

    class _Bundle:
        raw_text = "{}"
        parsed = {}
        meta = {"model": "qwen2.5:7b"}
        retry_count = 0

    def _bundle(prompt, **kwargs):
        captured.update(kwargs)
        return _Bundle()

    def _capture(crm, **kwargs):
        return InferenceRunRecord(
            id=1,
            procurement_id=1,
            run_kind=kwargs["run_kind"],
            parse_status="PARSED_OK",
            validation_status="VALIDATED_SUCCESS",
            raw_model_json={},
            validated_model_result={},
            raw_model_sha256="a",
            validated_model_sha256="b",
            validation_errors=[],
            prompt_version=kwargs.get("prompt_version"),
            model_name=kwargs.get("model_name"),
        )

    class _Engine:
        def load_registry(self):
            return [], set(), {}

        def build_prompt_context(self, procurement):
            return "p"

    monkeypatch.setattr(
        "src.services.commercial_routing_v3.shadow_inference.call_ollama_qwen_bundle",
        _bundle,
    )
    monkeypatch.setattr(
        "src.services.commercial_routing_v3.shadow_inference.capture_and_persist_inference_run",
        _capture,
    )
    monkeypatch.setattr(
        "src.services.commercial_routing_v3.shadow_inference.CommercialRoutingV3Engine",
        lambda crm_db=None: _Engine(),
    )

    run_shadow_inference(
        _Crm(),
        procurement_id=1,
        procurement={"title": "x"},
        prompt_text="p",
        compute_business_preview=False,
        dry_run_persist=True,
        acquire_gpu=False,
    )
    assert captured.get("experiment_model") is None
