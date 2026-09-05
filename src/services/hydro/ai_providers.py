"""Provider-neutral commercial assessment adapters for the Hydro shadow path."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from src.services.ai_client import generate_json_with_meta

from .commercial_hierarchy import validate_shadow_result


@dataclass(frozen=True)
class CommercialAssessmentInput:
    entity_key: str
    input_hash: str
    prompt: str


@dataclass(frozen=True)
class CommercialAssessmentResult:
    result: dict[str, Any]
    provider: str
    model: str
    latency_sec: float
    usage: dict[str, Any]


class CommercialAssessmentProvider(Protocol):
    provider_name: str
    model: str

    def assess(self, request: CommercialAssessmentInput, *, timeout: int, max_tokens: int) -> CommercialAssessmentResult:
        ...


class LocalQwenProvider:
    provider_name = "ollama"

    def __init__(self, model: str = "qwen2.5:7b") -> None:
        self.model = model

    def assess(self, request: CommercialAssessmentInput, *, timeout: int, max_tokens: int) -> CommercialAssessmentResult:
        started = time.monotonic()
        result, meta = generate_json_with_meta(request.prompt, model=self.model, timeout=timeout, num_predict=max_tokens)
        return CommercialAssessmentResult(validate_shadow_result(result), self.provider_name, meta.get("model") or self.model, time.monotonic() - started, meta)


class OpenRouterProvider:
    provider_name = "openrouter"
    endpoint = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat")
        if not self.model.startswith("deepseek/"):
            raise ValueError("OpenRouter Hydro provider accepts only deepseek/* models")

    def assess(self, request: CommercialAssessmentInput, *, timeout: int, max_tokens: int) -> CommercialAssessmentResult:
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": request.prompt}],
            "temperature": 0.15,
            "max_tokens": int(max_tokens),
            "stream": False,
            "response_format": {"type": "json_object"},
            "provider": {
                "data_collection": "deny",
                "zdr": True,
                "require_parameters": True,
            },
        }
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(http_request, timeout=timeout) as response:
                response_body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"OpenRouter request failed: {type(exc).__name__}") from exc
        try:
            content = response_body["choices"][0]["message"]["content"]
            result = validate_shadow_result(json.loads(content))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError("OpenRouter returned invalid commercial assessment JSON") from exc
        usage = response_body.get("usage") if isinstance(response_body.get("usage"), dict) else {}
        return CommercialAssessmentResult(result, self.provider_name, response_body.get("model") or self.model, time.monotonic() - started, usage)
