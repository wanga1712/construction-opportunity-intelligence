"""Immutable V3 model inference run persistence (Phase 6A).

RAW = exact Ollama response text (UTF-8 SHA256).
VALIDATED = schema/type/enum-only interpretation (no commercial invention).
Business enrichment happens only AFTER the run is inserted.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from src.services.commercial_routing_v3.model_json import prompt_sha256
from src.services.commercial_routing_v3.model_result_validator import (
    SCHEMA_VERSION_MODEL_VALIDATED,
    validate_model_result,
)
from src.services.commercial_routing_v3.prompt import PROMPT_VERSION

logger = logging.getLogger("commercial_routing_v3.model_inference_runs")

RUN_KIND_PRODUCTION = "PRODUCTION"
RUN_KIND_SHADOW = "SHADOW"

_IMMUTABLE_COLUMNS = frozenset(
    {
        "raw_model_text",
        "raw_model_sha256",
        "raw_model_json",
        "validated_model_result",
        "validated_model_sha256",
        "prompt_hash",
        "procurement_id",
        "run_kind",
    }
)


def raw_model_sha256(raw_text: str) -> str:
    """SHA256 of exact Ollama response text UTF-8 bytes."""
    return hashlib.sha256((raw_text or "").encode("utf-8")).hexdigest()


def canonical_json_bytes(obj: Any) -> bytes:
    """Deterministic JSON serialization for validated hash."""
    return json.dumps(
        obj,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def validated_model_sha256(validated: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(validated)).hexdigest()


@dataclass
class InferenceRunRecord:
    id: Optional[int] = None
    procurement_id: Optional[int] = None
    run_kind: str = RUN_KIND_PRODUCTION
    model_name: Optional[str] = None
    model_version: Optional[str] = None
    prompt_version: Optional[str] = None
    schema_version: Optional[str] = None
    prompt_hash: Optional[str] = None
    raw_model_text: Optional[str] = None
    raw_model_sha256: Optional[str] = None
    raw_model_json: Optional[Dict[str, Any]] = None
    parse_status: str = "NOT_ATTEMPTED"
    validated_model_result: Optional[Dict[str, Any]] = None
    validated_model_sha256: Optional[str] = None
    validation_status: str = "NOT_ATTEMPTED"
    validation_errors: List[str] = field(default_factory=list)
    ollama_metadata: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    source_attempt_id: Optional[int] = None
    run_status: str = "OPEN"


def assert_inference_run_immutable_update(columns: Dict[str, Any]) -> None:
    """Application-layer guard: refuse updates of immutable payload columns."""
    bad = sorted(_IMMUTABLE_COLUMNS.intersection(columns.keys()))
    if bad:
        raise RuntimeError(
            f"MODEL_RAW_MUTATED_AFTER_INFERENCE blocked; refused columns={bad}"
        )


def insert_inference_run(crm_db, record: InferenceRunRecord, *, dry_run: bool = False) -> Optional[int]:
    """Append-only INSERT. Never UPDATE raw/validated payload."""
    if dry_run or crm_db is None:
        return None
    try:
        ready = bool(
            crm_db.execute_scalar(
                "SELECT to_regclass('public.crm_v3_model_inference_runs') IS NOT NULL"
            )
        )
    except Exception:
        return None
    if not ready:
        logger.warning("crm_v3_model_inference_runs not ready; skip persist")
        return None

    raw_json = record.raw_model_json
    if raw_json is not None and not isinstance(raw_json, str):
        raw_json = json.dumps(raw_json, ensure_ascii=False, default=str)
    validated = record.validated_model_result
    if validated is not None and not isinstance(validated, str):
        validated = json.dumps(validated, ensure_ascii=False, default=str)
    errors = record.validation_errors or []
    if not isinstance(errors, str):
        errors = json.dumps(errors, ensure_ascii=False, default=str)
    meta = record.ollama_metadata or {}
    if not isinstance(meta, str):
        meta = json.dumps(meta, ensure_ascii=False, default=str)

    rows = crm_db.execute_query(
        """
        INSERT INTO crm_v3_model_inference_runs (
            procurement_id, run_kind, model_name, model_version,
            prompt_version, schema_version, prompt_hash,
            raw_model_text, raw_model_sha256, raw_model_json, parse_status,
            validated_model_result, validated_model_sha256,
            validation_status, validation_errors,
            ollama_metadata, retry_count, source_attempt_id, run_status
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s::jsonb, %s,
            %s::jsonb, %s,
            %s, %s::jsonb,
            %s::jsonb, %s, %s, %s
        )
        RETURNING id
        """,
        (
            record.procurement_id,
            record.run_kind,
            record.model_name,
            record.model_version,
            record.prompt_version,
            record.schema_version,
            record.prompt_hash,
            record.raw_model_text,
            record.raw_model_sha256,
            raw_json,
            record.parse_status,
            validated,
            record.validated_model_sha256,
            record.validation_status,
            errors,
            meta,
            int(record.retry_count or 0),
            record.source_attempt_id,
            record.run_status,
        ),
    )
    if not rows:
        return None
    row = rows[0]
    return int(row["id"] if isinstance(row, dict) else row[0])


def build_run_from_ollama(
    *,
    procurement_id: Any,
    run_kind: str,
    prompt: str,
    raw_text: Optional[str],
    parsed: Optional[Dict[str, Any]],
    parse_error: Optional[str],
    model_call_failed: bool,
    ollama_metadata: Optional[Dict[str, Any]],
    retry_count: int,
    allowed_categories: Set[str],
    allowed_subcategories: Optional[Dict[str, Set[str]]] = None,
    model_name: Optional[str] = None,
    prompt_version: Optional[str] = None,
    schema_version: Optional[str] = None,
) -> InferenceRunRecord:
    """Construct immutable run payload BEFORE business enrichment."""
    meta = dict(ollama_metadata or {})
    # Never let telemetry bleed into model JSON namespace.
    clean_parsed: Optional[Dict[str, Any]] = None
    if isinstance(parsed, dict):
        clean_parsed = {
            k: v for k, v in parsed.items() if not str(k).startswith("_")
        }

    rec = InferenceRunRecord(
        procurement_id=int(procurement_id) if procurement_id is not None else None,
        run_kind=run_kind,
        model_name=model_name or meta.get("model") or meta.get("request_model"),
        model_version=model_name or meta.get("model") or meta.get("request_model"),
        prompt_version=prompt_version or PROMPT_VERSION,
        schema_version=schema_version or SCHEMA_VERSION_MODEL_VALIDATED,
        prompt_hash=prompt_sha256(prompt),
        ollama_metadata=meta,
        retry_count=int(retry_count or 0),
    )

    if model_call_failed:
        rec.parse_status = "MODEL_CALL_FAILED"
        rec.validation_status = "NOT_ATTEMPTED"
        rec.run_status = "MODEL_CALL_FAILED"
        if raw_text is not None:
            rec.raw_model_text = raw_text
            rec.raw_model_sha256 = raw_model_sha256(raw_text)
        return rec

    if raw_text is None:
        rec.parse_status = "MODEL_CALL_FAILED"
        rec.validation_status = "NOT_ATTEMPTED"
        rec.run_status = "MODEL_CALL_FAILED"
        return rec

    rec.raw_model_text = raw_text
    rec.raw_model_sha256 = raw_model_sha256(raw_text)

    if clean_parsed is None:
        rec.parse_status = "RAW_RECEIVED_PARSE_FAILED"
        rec.validation_status = "NOT_ATTEMPTED"
        rec.validation_errors = [parse_error or "parse_failed"]
        rec.run_status = "RAW_RECEIVED_PARSE_FAILED"
        return rec

    rec.raw_model_json = clean_parsed
    rec.parse_status = "PARSED_OK"

    vr = validate_model_result(
        clean_parsed,
        allowed_categories=allowed_categories,
        allowed_subcategories=allowed_subcategories,
    )
    rec.validation_errors = list(vr.errors or [])
    if vr.status != "VALIDATED_SUCCESS" or vr.validated is None:
        rec.validation_status = "PARSED_SCHEMA_INVALID"
        rec.run_status = "PARSED_SCHEMA_INVALID"
        return rec

    rec.validated_model_result = vr.validated
    rec.validated_model_sha256 = validated_model_sha256(vr.validated)
    rec.validation_status = "VALIDATED_SUCCESS"
    rec.run_status = "VALIDATED_SUCCESS"
    return rec


def capture_and_persist_inference_run(
    crm_db,
    *,
    procurement_id: Any,
    run_kind: str,
    prompt: str,
    raw_text: Optional[str],
    parsed: Optional[Dict[str, Any]],
    parse_error: Optional[str] = None,
    model_call_failed: bool = False,
    ollama_metadata: Optional[Dict[str, Any]] = None,
    retry_count: int = 0,
    allowed_categories: Optional[Set[str]] = None,
    allowed_subcategories: Optional[Dict[str, Set[str]]] = None,
    model_name: Optional[str] = None,
    prompt_version: Optional[str] = None,
    dry_run: bool = False,
) -> InferenceRunRecord:
    """Validate + INSERT immutable run before any business enrichment."""
    cats = set(allowed_categories or set())
    rec = build_run_from_ollama(
        procurement_id=procurement_id,
        run_kind=run_kind,
        prompt=prompt,
        raw_text=raw_text,
        parsed=parsed,
        parse_error=parse_error,
        model_call_failed=model_call_failed,
        ollama_metadata=ollama_metadata,
        retry_count=retry_count,
        allowed_categories=cats,
        allowed_subcategories=allowed_subcategories,
        model_name=model_name,
        prompt_version=prompt_version,
    )
    run_id = insert_inference_run(crm_db, rec, dry_run=dry_run)
    rec.id = run_id
    return rec
