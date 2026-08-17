"""Tests for V3 model resolver + GPU health probes."""
from __future__ import annotations

import os

import pytest

from src.services.ai_client import (
    UnexpectedProductionModelError,
    assert_production_v3_model,
    v3_routing_model,
)


def test_v3_routing_model_ignores_ollama_model_14b(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:14b")
    monkeypatch.delenv("CRM_V3_ROUTING_MODEL", raising=False)
    monkeypatch.delenv("CRM_V3_CANARY_MODEL", raising=False)
    assert v3_routing_model() == "qwen2.5:7b"


def test_assert_production_v3_model_fail_closed_14b(monkeypatch):
    monkeypatch.setenv("CRM_V3_ROUTING_MODEL", "qwen2.5:14b")
    with pytest.raises(UnexpectedProductionModelError):
        assert_production_v3_model()


def test_assert_production_v3_model_7b_ok(monkeypatch):
    monkeypatch.delenv("CRM_V3_ROUTING_MODEL", raising=False)
    monkeypatch.delenv("CRM_V3_CANARY_MODEL", raising=False)
    assert assert_production_v3_model() == "qwen2.5:7b"


def test_v3_routing_model_attribute_exists():
    import src.services.ai_client as ai_client

    assert hasattr(ai_client, "v3_routing_model")
    assert callable(ai_client.v3_routing_model)


def test_gpu_collector_shape():
    from src.services.system_health_gpu import collect_nvidia_gpu, collect_ollama_status

    g = collect_nvidia_gpu()
    assert "gpu_available" in g
    assert "gpu_util_percent" in g
    # Unsupported must not be forced to 0 when unavailable — if unavailable, None
    if not g["gpu_available"]:
        assert g["gpu_util_percent"] is None
    o = collect_ollama_status(g)
    assert "OLLAMA_EXECUTION_MODE" in o
    assert o["OLLAMA_EXECUTION_MODE"] in ("GPU", "PARTIAL_GPU", "CPU", "IDLE", "UNKNOWN")


def test_generate_v3_routing_uses_canonical_model(monkeypatch):
    """Regression: production path must not inherit OLLAMA_MODEL=14b."""
    from src.services import ai_client

    captured = {}

    def fake_generate_with_meta(prompt, model=None, **kwargs):
        captured["model"] = model
        return '{"ok": true}', {"model": model}

    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:14b")
    monkeypatch.delenv("CRM_V3_ROUTING_MODEL", raising=False)
    monkeypatch.setattr(ai_client, "generate_with_meta", fake_generate_with_meta)
    text, meta = ai_client.generate_v3_routing("{}", timeout=5)
    assert captured.get("model") == "qwen2.5:7b"
    assert meta.get("request_model") == "qwen2.5:7b"
    assert text


def test_unexpected_model_no_v2_fallback(monkeypatch):
    monkeypatch.setenv("CRM_V3_ROUTING_MODEL", "qwen2.5:3b")
    with pytest.raises(UnexpectedProductionModelError):
        assert_production_v3_model("qwen2.5:3b")
