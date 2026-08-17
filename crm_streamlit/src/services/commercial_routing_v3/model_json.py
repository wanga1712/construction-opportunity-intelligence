"""Deterministic V3 model JSON extraction and format-failure classification.

Extraction recovers framing (fences, whitespace, prefix/suffix prose).
It must not invent or repair commercial fields.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

V3_INFERENCE_MAX_ATTEMPTS = 3
V3_INFERENCE_STATE_FORMAT_FAILED = "MODEL_INFERENCE_FORMAT_FAILED"
STRUCTURED_OUTPUT_MODE_JSON = "ollama_format_json"
NUM_PREDICT_TRUNCATION_RETRY = 1536
TRUNCATION_RETRY_REASON = (
    "attempt_3_num_predict_bump_on_TRUNCATED_RESPONSE_only; "
    "default NUM_PREDICT stays 512; semantic prompt/model/input unchanged; "
    "ceiling 1536 for reproducible generation-limit truncations"
)

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


RETRYABLE_FORMAT_CLASSES = frozenset(
    {
        "EMPTY_RESPONSE",
        "TRUNCATED_RESPONSE",
        "MARKDOWN_FENCED_JSON",
        "JSON_PREFIX_SUFFIX_TEXT",
        "INVALID_JSON_SYNTAX",
        "SCHEMA_INVALID_JSON",
        "TIMEOUT",
        "OLLAMA_TRANSPORT_ERROR",
        "OTHER",
    }
)


class ModelFormatError(ValueError):
    def __init__(self, failure_class: str, message: str, *, raw_length: int = 0):
        super().__init__(message)
        self.failure_class = failure_class
        self.raw_length = raw_length


class ModelInferenceFormatFailed(RuntimeError):
    """Persistent format failure after the canonical attempt budget."""

    def __init__(
        self,
        message: str,
        *,
        durable_state: Dict[str, Any],
        attempt_history: List[Dict[str, Any]],
        meta: Dict[str, Any],
    ):
        super().__init__(message)
        self.durable_state = durable_state
        self.attempt_history = attempt_history
        self.meta = meta
        self.failure_class = str(durable_state.get("failure_class") or "OTHER")


def prompt_sha256(prompt: str) -> str:
    return hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()


def classify_format_failure(text: str, *, exc: Optional[BaseException] = None) -> str:
    if exc is not None:
        msg = str(exc).lower()
        if "timed out" in msg or "timeout" in msg:
            return "TIMEOUT"
        if "unable to reach ollama" in msg or "urlerror" in msg or "http " in msg:
            return "OLLAMA_TRANSPORT_ERROR"
    raw = text if text is not None else ""
    stripped = raw.strip()
    if not stripped:
        return "EMPTY_RESPONSE"
    if stripped.startswith("```"):
        return "MARKDOWN_FENCED_JSON"
    if "{" in stripped and not stripped.startswith("{"):
        return "JSON_PREFIX_SUFFIX_TEXT"
    if stripped.startswith("{") and stripped.count("{") > stripped.count("}"):
        return "TRUNCATED_RESPONSE"
    if stripped.startswith("{") or stripped.startswith("["):
        return "INVALID_JSON_SYNTAX"
    return "OTHER"


def _balanced_object(text: str) -> Optional[str]:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_routing_json(text: str) -> Tuple[Dict[str, Any], str]:
    """Return (object, extraction_method). Raises ModelFormatError."""
    raw_length = len(text or "")
    if text is None or not str(text).strip():
        raise ModelFormatError("EMPTY_RESPONSE", "empty model response", raw_length=raw_length)
    raw = str(text).strip()
    candidates: List[Tuple[str, str]] = [("raw", raw)]
    fence = _FENCE_RE.search(raw)
    if fence:
        candidates.append(("markdown_fence", fence.group(1).strip()))
    balanced = _balanced_object(raw)
    if balanced:
        candidates.append(("balanced_object", balanced))
    last_err: Optional[Exception] = None
    for method, candidate in candidates:
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_err = exc
            continue
        if isinstance(value, dict):
            return value, method
        raise ModelFormatError(
            "SCHEMA_INVALID_JSON",
            "JSON is not an object",
            raw_length=raw_length,
        )
    failure = classify_format_failure(raw, exc=last_err)
    raise ModelFormatError(failure, "model response is not a JSON object", raw_length=raw_length)


def empty_attempt_record(*, status: str, failure_class: Optional[str] = None) -> Dict[str, Any]:
    return {
        "status": status,
        "failure_class": failure_class,
        "raw_response_length": 0,
        "extraction_method": None,
    }


def durable_format_failed_state(
    *,
    procurement_id: Any,
    attempt_count: int,
    input_hash: Optional[str],
    prompt_version: str,
    model: str,
    failure_reason: str,
    failure_class: str,
    last_attempt_at: str,
    next_retry_at: Optional[str] = None,
    attempt_history: Optional[List[Dict[str, Any]]] = None,
    prompt_sha256: Optional[str] = None,
    workload_type: str = "ROUTING",
) -> Dict[str, Any]:
    return {
        "status": V3_INFERENCE_STATE_FORMAT_FAILED,
        "procurement_id": procurement_id,
        "attempt_count": attempt_count,
        "last_attempt_at": last_attempt_at,
        "next_retry_at": next_retry_at,
        "retry_eligible": True,
        "input_hash": input_hash,
        "prompt_version": prompt_version,
        "prompt_sha256": prompt_sha256,
        "model": model,
        "failure_reason": failure_reason,
        "failure_class": failure_class,
        "attempt_history": list(attempt_history or []),
        "workload_type": workload_type,
    }
