"""Shared HTTP client for the local Ollama service."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

from src.services.commercial_routing_v3.model_json import (
    NUM_PREDICT_TRUNCATION_RETRY,
    RETRYABLE_FORMAT_CLASSES,
    STRUCTURED_OUTPUT_MODE_JSON,
    TRUNCATION_RETRY_REASON,
    V3_INFERENCE_MAX_ATTEMPTS,
    ModelFormatError,
    ModelInferenceFormatFailed,
    classify_format_failure,
    durable_format_failed_state,
    extract_routing_json,
    prompt_sha256,
)

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:7b"
# V3 commercial routing must not silently inherit stale OLLAMA_MODEL=14b.
DEFAULT_V3_ROUTING_MODEL = "qwen2.5:7b"
PRODUCTION_V3_ALLOWED_MODELS = frozenset({"qwen2.5:7b"})


class UnexpectedProductionModelError(RuntimeError):
    """Production V3 refuse unexpected model (fail-closed)."""


def _settings(model: str | None) -> tuple[str, str]:
    base_url = os.getenv("OLLAMA_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    selected_model = model or os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
    return base_url, selected_model


def configured_model() -> str:
    """Return the model selected by the shared client configuration."""
    return _settings(None)[1]


def v3_routing_model(explicit: str | None = None) -> str:
    """Canonical model for V3 commercial routing / golden canary.

    Precedence: explicit → CRM_V3_ROUTING_MODEL → CRM_V3_CANARY_MODEL → qwen2.5:7b.
    Does NOT fall back to OLLAMA_MODEL (may be stale 14b).
    """
    if explicit:
        return explicit
    return (
        os.getenv("CRM_V3_ROUTING_MODEL")
        or os.getenv("CRM_V3_CANARY_MODEL")
        or DEFAULT_V3_ROUTING_MODEL
    )


def assert_production_v3_model(model: str | None = None) -> str:
    """Fail-closed: production V3 accepts only qwen2.5:7b."""
    resolved = v3_routing_model(model)
    if resolved not in PRODUCTION_V3_ALLOWED_MODELS:
        raise UnexpectedProductionModelError(
            f"Production V3 refuses model={resolved!r}; allowed={sorted(PRODUCTION_V3_ALLOWED_MODELS)}"
        )
    return resolved


def generate(
    prompt: str,
    *,
    model: str | None = None,
    timeout: int = 75,
    num_predict: int | None = None,
    format_json: bool = False,
) -> str:
    """Return a non-streaming Ollama completion for *prompt*."""
    text, _meta = generate_with_meta(
        prompt,
        model=model,
        timeout=timeout,
        num_predict=num_predict,
        format_json=format_json,
    )
    return text


def generate_with_meta(
    prompt: str,
    *,
    model: str | None = None,
    timeout: int = 75,
    num_predict: int | None = None,
    format_json: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Return completion text plus Ollama timing/token meta."""
    base_url, selected_model = _settings(model)
    body: dict[str, Any] = {
        "model": selected_model,
        "prompt": prompt,
        "stream": False,
    }
    # Keep model resident during backlog drain / continuous routing (ops only).
    keep_alive = os.getenv("CRM_V3_OLLAMA_KEEP_ALIVE", "30m").strip()
    if keep_alive:
        # Ollama accepts duration strings ("30m") or seconds; "-1" = forever.
        if keep_alive.lstrip("-").isdigit():
            body["keep_alive"] = int(keep_alive)
        else:
            body["keep_alive"] = keep_alive
    options: dict[str, Any] = {}
    if num_predict is not None:
        options["num_predict"] = int(num_predict)
    if options:
        body["options"] = options
    if format_json:
        body["format"] = "json"
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
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

    def _ns_to_sec(v: Any) -> Optional[float]:
        try:
            return float(v) / 1e9
        except (TypeError, ValueError):
            return None

    meta = {
        "model": data.get("model") or selected_model,
        "prompt_eval_count": data.get("prompt_eval_count"),
        "eval_count": data.get("eval_count"),
        "prompt_eval_duration_sec": _ns_to_sec(data.get("prompt_eval_duration")),
        "eval_duration_sec": _ns_to_sec(data.get("eval_duration")),
        "total_duration_sec": _ns_to_sec(data.get("total_duration")),
        "num_predict": num_predict,
        "generation_endpoint": f"{base_url}/api/generate",
        "structured_output_requested": bool(format_json),
        "structured_output_mode": STRUCTURED_OUTPUT_MODE_JSON if format_json else None,
    }
    return answer, meta


def generate_v3_routing(
    prompt: str,
    *,
    timeout: int = 600,
    num_predict: int | None = None,
    format_json: bool = True,
    experiment_model: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Production V3 routing inference — fail-closed to qwen2.5:7b.

    experiment_model is only for explicitly named experiment callers; production
    must leave it None so assert_production_v3_model enforces 7b.
    """
    if experiment_model:
        # Explicit experiment path — not production.
        model = experiment_model
    else:
        model = assert_production_v3_model()
    text, meta = generate_with_meta(
        prompt,
        model=model,
        timeout=timeout,
        num_predict=num_predict,
        format_json=format_json,
    )
    proven = str(meta.get("model") or model)
    if experiment_model is None:
        if proven != "qwen2.5:7b" and not proven.startswith("qwen2.5:7b"):
            raise UnexpectedProductionModelError(
                f"Ollama request/response model not production 7b: {proven!r}"
            )
    meta["production_v3_model_contract"] = "qwen2.5:7b"
    meta["request_model"] = model
    return text, meta


def _extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from plain text, markdown fences, or prefix/suffix prose."""
    parsed, _method = extract_routing_json(text)
    return parsed


def extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object previously returned by the model."""
    return _extract_json(text)


def generate_v3_routing_with_bounded_retry(
    prompt: str,
    *,
    timeout: int = 600,
    num_predict: int | None = None,
    format_json: bool = True,
    experiment_model: str | None = None,
    max_attempts: int = V3_INFERENCE_MAX_ATTEMPTS,
    input_hash: str | None = None,
    prompt_version: str | None = None,
    procurement_id: Any = None,
) -> tuple[dict[str, Any], dict[str, Any], int]:
    """Canonical V3 inference: structured JSON, same semantic input, bounded retries.

    Returns (parsed_json, meta, model_format_retry_count).
    retry_count is attempt_count-1 on both success and persistent failure
    (recorded on ModelInferenceFormatFailed.meta).
    """
    prompt_hash = prompt_sha256(prompt)
    request_model = experiment_model or assert_production_v3_model()
    history: list[dict[str, Any]] = []
    last_failure_class = "OTHER"
    last_error: Exception | None = None
    last_meta: dict[str, Any] = {}
    last_raw_text: str | None = None
    attempts_used = 0

    for attempt in range(1, int(max_attempts) + 1):
        attempts_used = attempt
        attempt_predict = num_predict
        attempt_options_note = "same_as_attempt_1"
        if (
            attempt == int(max_attempts)
            and last_failure_class == "TRUNCATED_RESPONSE"
            and (num_predict or 0) < NUM_PREDICT_TRUNCATION_RETRY
        ):
            attempt_predict = NUM_PREDICT_TRUNCATION_RETRY
            attempt_options_note = TRUNCATION_RETRY_REASON
        try:
            # RAW capture point: exact Ollama response text before any mutation.
            raw_text, meta = generate_v3_routing(
                prompt,
                timeout=timeout,
                num_predict=attempt_predict,
                format_json=format_json,
                experiment_model=experiment_model,
            )
            last_raw_text = raw_text
        except Exception as exc:
            last_error = exc
            last_failure_class = classify_format_failure("", exc=exc)
            rec = {
                "attempt": attempt,
                "status": "FAIL",
                "failure_class": last_failure_class,
                "raw_response_length": 0,
                "extraction_method": None,
                "num_predict": attempt_predict,
                "format_json": format_json,
                "options_note": attempt_options_note,
                "error": str(exc),
            }
            history.append(rec)
            last_meta = {
                "model": request_model,
                "request_model": request_model,
                "num_predict": attempt_predict,
            }
            if attempt < int(max_attempts) and last_failure_class in RETRYABLE_FORMAT_CLASSES:
                continue
            break
        try:
            parsed, method = extract_routing_json(raw_text)
        except ModelFormatError as exc:
            last_error = exc
            last_failure_class = exc.failure_class
            history.append(
                {
                    "attempt": attempt,
                    "status": "FAIL",
                    "failure_class": exc.failure_class,
                    "raw_response_length": exc.raw_length,
                    "extraction_method": None,
                    "num_predict": attempt_predict,
                    "format_json": format_json,
                    "options_note": attempt_options_note,
                    "error": str(exc),
                }
            )
            last_meta = dict(meta)
            last_meta["raw_text"] = raw_text
            if attempt < int(max_attempts):
                continue
            break
        retries = attempt - 1
        meta = dict(meta)
        meta.update(
            {
                "raw_text": raw_text,
                "model_format_retry_count": retries,
                "attempt_count": attempt,
                "attempt_history": history
                + [
                    {
                        "attempt": attempt,
                        "status": "OK",
                        "failure_class": None,
                        "raw_response_length": len(raw_text or ""),
                        "extraction_method": method,
                        "num_predict": attempt_predict,
                        "format_json": format_json,
                        "options_note": attempt_options_note,
                    }
                ],
                "prompt_sha256": prompt_hash,
                "input_hash": input_hash,
                "same_prompt_hash": True,
                "same_model_input_hash": True,
                "same_model": True,
                "structured_output_used": bool(format_json),
                "structured_output_mode": STRUCTURED_OUTPUT_MODE_JSON if format_json else None,
            }
        )
        return parsed, meta, retries

    retries = max(0, attempts_used - 1)
    ts = datetime.now(timezone.utc).isoformat()
    durable = durable_format_failed_state(
        procurement_id=procurement_id,
        attempt_count=attempts_used,
        input_hash=input_hash,
        prompt_version=str(prompt_version or ""),
        model=str(last_meta.get("model") or request_model),
        failure_reason=str(last_error or last_failure_class),
        failure_class=last_failure_class,
        last_attempt_at=ts,
        attempt_history=history,
        prompt_sha256=prompt_hash,
        workload_type="ROUTING",
    )
    fail_meta = dict(last_meta)
    fail_meta.update(
        {
            "raw_text": last_raw_text,
            "model_format_retry_count": retries,
            "attempt_count": attempts_used,
            "attempt_history": history,
            "prompt_sha256": prompt_hash,
            "input_hash": input_hash,
            "same_prompt_hash": True,
            "same_model_input_hash": True,
            "same_model": True,
            "structured_output_used": bool(format_json),
            "durable_format_failed_state": durable,
        }
    )
    raise ModelInferenceFormatFailed(
        f"{durable['status']}: {last_failure_class}",
        durable_state=durable,
        attempt_history=history,
        meta=fail_meta,
    )


def generate_json(
    prompt: str,
    *,
    model: str | None = None,
    timeout: int = 75,
    num_predict: int | None = None,
    format_json: bool = True,
) -> dict[str, Any]:
    """Generate text and extract a JSON object from the model response."""
    obj, _meta = generate_json_with_meta(
        prompt,
        model=model,
        timeout=timeout,
        num_predict=num_predict,
        format_json=format_json,
    )
    return obj


def generate_json_with_meta(
    prompt: str,
    *,
    model: str | None = None,
    timeout: int = 75,
    num_predict: int | None = None,
    format_json: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Generate JSON and return (object, ollama_meta)."""
    text, meta = generate_with_meta(
        prompt,
        model=model,
        timeout=timeout,
        num_predict=num_predict,
        format_json=format_json,
    )
    return _extract_json(text), meta
