"""Regression: JSON parse failures must not be labeled OLLAMA_TIMEOUT."""
from __future__ import annotations

import pytest

from src.services.ai_assessment_runner import OllamaJsonParseError, call_ollama_qwen
from src.services.commercial_routing_v3.routing_runtime_config import RoutingErrorClass


def test_call_ollama_qwen_raises_json_parse_error(monkeypatch):
    from src.services import ai_assessment_runner as mod

    def fake_gen(prompt, timeout=600):
        return "not json at all {{{", {"model": "qwen2.5:7b", "request_model": "qwen2.5:7b", "total_duration_sec": 1.0}

    monkeypatch.setattr(
        "src.services.ai_client.generate_v3_routing",
        fake_gen,
    )

    with pytest.raises(OllamaJsonParseError):
        call_ollama_qwen("{}")


def test_call_ollama_qwen_timeout_returns_none(monkeypatch):
    def boom(prompt, timeout=600):
        raise TimeoutError("timed out")

    monkeypatch.setattr("src.services.ai_client.generate_v3_routing", boom)
    assert call_ollama_qwen("{}") is None


def test_invalid_json_error_class_distinct_from_timeout():
    assert RoutingErrorClass.INVALID_JSON != RoutingErrorClass.OLLAMA_TIMEOUT
    assert RoutingErrorClass.INVALID_JSON in {
        RoutingErrorClass.INVALID_JSON,
        RoutingErrorClass.OLLAMA_TIMEOUT,
    }
