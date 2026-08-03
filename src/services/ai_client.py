"""Shared HTTP client for the local Ollama service."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:7b"


def _settings(model: str | None) -> tuple[str, str]:
    base_url = os.getenv("OLLAMA_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    selected_model = model or os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
    return base_url, selected_model


def configured_model() -> str:
    """Return the model selected by the shared client configuration."""
    return _settings(None)[1]


def generate(prompt: str, *, model: str | None = None, timeout: int = 75) -> str:
    """Return a non-streaming Ollama completion for *prompt*."""
    base_url, selected_model = _settings(model)
    payload = json.dumps(
        {"model": selected_model, "prompt": prompt, "stream": False},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data: Any = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Unable to reach Ollama at {base_url}: {exc.reason}") from exc

    if not isinstance(data, dict):
        raise ValueError("Ollama returned an invalid response")
    answer = data.get("response")
    if not isinstance(answer, str):
        raise ValueError("Ollama response does not contain text")
    return answer


def _extract_json(text: str) -> dict[str, Any]:
    """Extract the first JSON object from plain text or a fenced response."""
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    candidates = (raw, raw[raw.find("{") : raw.rfind("}") + 1])
    for candidate in candidates:
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("model response is not a JSON object")


def extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object previously returned by the model."""
    return _extract_json(text)


def generate_json(
    prompt: str, *, model: str | None = None, timeout: int = 75
) -> dict[str, Any]:
    """Generate text and extract a JSON object from the model response."""
    return _extract_json(generate(prompt, model=model, timeout=timeout))
