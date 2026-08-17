"""One-shot V3 golden canary orchestration (boot-safe, max 4 procurements)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.services.ai_client import configured_model, generate_json
from src.services.commercial_routing_v3.engine import CommercialRoutingV3Engine
from src.services.commercial_routing_v3.golden_canary_config import (
    BATCH_ROUTING_TRIGGERED,
    CANARY_DIR,
    CANARY_ID,
    CANARY_RUN_MAX_ONCE,
    DOCUMENT_PROCESSING_RUN,
    MARKER_PATH,
    MAX_PROCUREMENTS_PROCESSED,
    QUEUE_GENERATED,
    READINESS_INITIAL_DELAY_SEC,
    READINESS_MAX_WAIT_SEC,
    REFERENCE_PATH,
    REPORT_PATH,
    STATUS_ARMED,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_PATH,
    STATUS_RUNNING,
    STATUS_SKIPPED,
    STATUS_WAITING,
)
from src.services.commercial_routing_v3.golden_canary_readiness import evaluate_readiness
from src.services.commercial_routing_v3.golden_canary_select import (
    load_procurement_for_routing,
    select_four_reference_cases,
)
from src.services.commercial_routing_v3.golden_canary_validate import (
    aggregate_verdict,
    validate_case,
)

logger = logging.getLogger("v3_golden_canary")

assert MAX_PROCUREMENTS_PROCESSED == 4
assert QUEUE_GENERATED is False
assert DOCUMENT_PROCESSING_RUN is False
assert BATCH_ROUTING_TRIGGERED is False
assert CANARY_RUN_MAX_ONCE is True

# Technical transport only: one bounded retry. No semantic retry.
# Canary prefers 7b for bounded latency; override with CRM_V3_CANARY_MODEL.
_CANARY_MODEL_TIMEOUT_SEC = 600
_CANARY_TRANSPORT_RETRIES = 1
_CANARY_DEFAULT_MODEL = "qwen2.5:7b"


def _canary_model_name() -> str:
    return os.getenv("CRM_V3_CANARY_MODEL") or _CANARY_DEFAULT_MODEL


def _generate_json_once(prompt: str, generate_json_fn: Callable[..., Dict[str, Any]]) -> Dict[str, Any]:
    last_exc: Optional[BaseException] = None
    attempts = 1 + _CANARY_TRANSPORT_RETRIES
    model = _canary_model_name()
    for i in range(attempts):
        try:
            try:
                return generate_json_fn(prompt, model=model, timeout=_CANARY_MODEL_TIMEOUT_SEC)
            except TypeError:
                # injected test doubles may not accept model=
                return generate_json_fn(prompt, timeout=_CANARY_MODEL_TIMEOUT_SEC)
        except (TimeoutError, OSError, RuntimeError, ValueError) as exc:
            last_exc = exc
            logger.warning(
                "canary model transport attempt %s/%s model=%s failed: %s",
                i + 1,
                attempts,
                model,
                type(exc).__name__,
            )
            if i + 1 >= attempts:
                break
    assert last_exc is not None
    raise last_exc


def ensure_canary_dir() -> None:
    CANARY_DIR.mkdir(parents=True, exist_ok=True)


def write_status(state: str, **extra: Any) -> None:
    ensure_canary_dir()
    payload = {
        "canary_id": CANARY_ID,
        "state": state,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_status() -> Dict[str, Any]:
    if not STATUS_PATH.exists():
        return {"state": "UNKNOWN"}
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"state": "UNREADABLE"}


def marker_exists() -> bool:
    return MARKER_PATH.exists()


def write_marker(final_verdict: str) -> None:
    ensure_canary_dir()
    MARKER_PATH.write_text(
        json.dumps(
            {
                "canary_id": CANARY_ID,
                "final_verdict": final_verdict,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def write_report(report: Dict[str, Any]) -> Path:
    ensure_canary_dir()
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    txt = REPORT_PATH.with_suffix(".txt")
    lines = [
        f"CANARY_ID={CANARY_ID}",
        f"FINAL={report.get('final_verdict')}",
        f"QWEN_PROCUREMENT_COUNT={report.get('qwen_procurement_count')}",
        f"SELECTED_IDS={report.get('selected_ids')}",
    ]
    for c in report.get("case_verdicts") or []:
        lines.append(f"CASE {c.get('case_key')} id={c.get('procurement_id')} {c.get('verdict')} {c.get('flags')}")
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return REPORT_PATH


def arm_status_only() -> Dict[str, Any]:
    """Tonight: write ARMED status without running Qwen."""
    ensure_canary_dir()
    write_status(
        STATUS_ARMED,
        detail=STATUS_WAITING,
        qwen_run_tonight=False,
        max_procurements=MAX_PROCUREMENTS_PROCESSED,
        marker=str(MARKER_PATH),
        report_path=str(REPORT_PATH),
    )
    return read_status()


def _decision_to_capture(decision) -> Dict[str, Any]:
    hyps = []
    for h in decision.commercial_category_hypotheses or []:
        sub = h.commercial_subcategory_code
        item = {
            "category_code": h.commercial_category_code,
            "subcategory_code": sub,
            "subcategory_status": "SUBCATEGORY_NOT_ASSIGNED" if not sub else "ASSIGNED",
            "opportunity_track": h.opportunity_track.value
            if hasattr(h.opportunity_track, "value")
            else h.opportunity_track,
            "candidate_medal": h.candidate_medal.value
            if hasattr(h.candidate_medal, "value")
            else h.candidate_medal,
            "confidence": h.category_confidence,
            "reason_codes": list(h.reason_codes or []),
            "positive_evidence": list(h.positive_evidence or []),
            "negative_evidence": list(h.negative_evidence or []),
            "research_action": h.research_action.value
            if hasattr(h.research_action, "value")
            else h.research_action,
        }
        hyps.append(item)
    return {
        "procurement_form": decision.procurement_form.value
        if hasattr(decision.procurement_form, "value")
        else decision.procurement_form,
        "commercial_category_hypotheses": hyps,
        "commercial_subcategory": [h["subcategory_code"] or "SUBCATEGORY_NOT_ASSIGNED" for h in hyps],
        "material_signals": list(decision.material_signals or []),
        "work_methods": list(decision.work_methods or []),
        "application_areas": list(decision.application_areas or []),
        "object_context": list(decision.object_context or []),
        "brands": list(decision.brands or []),
        "opportunity_track": [h["opportunity_track"] for h in hyps],
        "candidate_medal": [h["candidate_medal"] for h in hyps],
        "reason_codes": [h["reason_codes"] for h in hyps],
        "negative_evidence": [h["negative_evidence"] for h in hyps],
        "discovery_required": bool(decision.discovery_required),
        "review_required": False,
        "validation_status": "CAPTURED",
        "subcategory_explicit_ok": True,
        "prompt_version": decision.prompt_version,
        "routing_version": decision.routing_version,
        "model_name": decision.model_name,
        "registry_version": decision.registry_version,
        "registry_hash": decision.registry_hash,
    }


def run_golden_canary(
    *,
    crm_db,
    tender_db,
    execute_qwen: bool = False,
    skip_readiness_sleep: bool = False,
    ignore_marker: bool = False,
    generate_json_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    persist_db: bool = False,
    analytics_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Controlled canary.
    execute_qwen=False → select + reference + readiness only (no model).
    ignore_marker=True → allow today's manual run even if boot marker exists.
    """
    ensure_canary_dir()
    started = datetime.now(timezone.utc).isoformat()
    report: Dict[str, Any] = {
        "canary_id": CANARY_ID,
        "started_at": started,
        "execute_qwen": execute_qwen,
        "ignore_marker": ignore_marker,
        "max_procurements": MAX_PROCUREMENTS_PROCESSED,
        "QUEUE_GENERATED": False,
        "DOCUMENT_PROCESSING_RUN": False,
        "BATCH_ROUTING_TRIGGERED": False,
        "AI_TIMER_ENABLED_BY_CANARY": False,
        "S7_DB_WRITES": 0,
        "persist_db": persist_db,
        "REFERENCE_LABELS_DEFINED_BEFORE_QWEN": False,
        "qwen_procurement_count": 0,
        "selected_ids": [],
        "cases": [],
        "case_verdicts": [],
        "final_verdict": "FAIL",
        "PERSISTED_RESULTS": False,
        "PERSISTENCE_MODE": "REPORT_ONLY",
    }

    if marker_exists() and not ignore_marker:
        write_status(STATUS_SKIPPED, reason="marker_exists")
        report["final_verdict"] = STATUS_SKIPPED
        report["skipped"] = True
        write_report(report)
        return report

    write_status(STATUS_RUNNING, phase="readiness")

    readiness = evaluate_readiness(
        crm_db=crm_db,
        tender_db=tender_db,
        skip_sleep=skip_readiness_sleep,
    )
    report["readiness"] = readiness.to_dict()
    if not readiness.ok:
        report["final_verdict"] = "FAIL"
        report["fail_reason"] = "READINESS_GATE"
        write_status(STATUS_FAIL, reason="readiness", failures=readiness.failures)
        # Manual/select failures must NOT write durable boot marker (would block retries incorrectly).
        if not ignore_marker and execute_qwen:
            write_marker("FAIL")
        write_report(report)
        return report

    # Select + reference BEFORE any model call
    write_status(STATUS_RUNNING, phase="select_reference")
    engine = CommercialRoutingV3Engine(crm_db=crm_db)
    priors = engine._load_priors()
    refs = select_four_reference_cases(crm_db, priors=priors)
    if len(refs) != MAX_PROCUREMENTS_PROCESSED:
        raise RuntimeError("MAX_PROCUREMENTS_VIOLATION_ON_SELECT")

    ref_payload = [r.to_dict() for r in refs]
    REFERENCE_PATH.write_text(
        json.dumps(ref_payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    report["REFERENCE_LABELS_DEFINED_BEFORE_QWEN"] = True
    report["reference_path"] = str(REFERENCE_PATH)
    report["selected_ids"] = [r.procurement_id for r in refs]
    report["references"] = ref_payload
    assert all(r.before_qwen for r in refs)

    if not execute_qwen:
        report["final_verdict"] = "ARMED_SELECT_ONLY"
        report["qwen_procurement_count"] = 0
        write_status(STATUS_ARMED, detail=STATUS_WAITING, selected_ids=report["selected_ids"])
        write_report(report)
        # Do NOT write .done marker on select-only arm
        return report

    # Hard cap
    to_process = refs[:MAX_PROCUREMENTS_PROCESSED]
    assert len(to_process) == 4

    gen = generate_json_fn or generate_json
    model_name = _canary_model_name()
    registry, allowed, _subs = engine.load_registry()
    registry_hash = f"cats={len(registry)}"

    case_outputs: List[Dict[str, Any]] = []
    case_verdicts: List[Dict[str, Any]] = []
    raw_hashes: List[Dict[str, Any]] = []

    try:
        for ref in to_process:
            write_status(STATUS_RUNNING, phase="qwen", procurement_id=ref.procurement_id, case=ref.case_key)
            proc = load_procurement_for_routing(crm_db, ref.procurement_id)
            prompt = engine.build_prompt_context(proc)
            raw = _generate_json_once(prompt, gen)
            if not isinstance(raw, dict):
                raise RuntimeError("MODEL_NON_JSON")
            raw_blob = json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str)
            raw_hash = hashlib.sha256(raw_blob.encode("utf-8")).hexdigest()
            raw_path = CANARY_DIR / f"{CANARY_ID}.raw.{ref.case_key}.json"
            raw_path.write_text(raw_blob, encoding="utf-8")
            raw_hashes.append({"case_key": ref.case_key, "sha256": raw_hash, "path": str(raw_path)})

            decision = engine.route_with_ai(
                proc,
                raw,
                registry_version=1,
                registry_hash=registry_hash,
                model_name=model_name,
            )
            capture = _decision_to_capture(decision)
            capture["raw_keys"] = sorted(raw.keys())
            capture["raw_sha256"] = raw_hash
            verdict = validate_case(ref, capture, allowed_categories=allowed)
            case_outputs.append(
                {
                    "reference": ref.to_dict(),
                    "procurement_input": {
                        "id": proc.get("id"),
                        "title": proc.get("title"),
                        "okpd_code": proc.get("okpd_code"),
                        "okpd_name": proc.get("okpd_name"),
                        "price": proc.get("price"),
                        "source_table": proc.get("source_table"),
                        "source_id": proc.get("source_id"),
                        "crm_stage": proc.get("crm_stage"),
                        "customer": proc.get("customer"),
                    },
                    "model_output": capture,
                    "verdict": verdict,
                }
            )
            case_verdicts.append(verdict)
            report["qwen_procurement_count"] += 1
            if report["qwen_procurement_count"] > MAX_PROCUREMENTS_PROCESSED:
                raise RuntimeError("MAX_PROCUREMENTS_EXCEEDED")
    except Exception as exc:
        report["cases"] = case_outputs
        report["case_verdicts"] = case_verdicts
        report["raw_hashes"] = raw_hashes
        report["final_verdict"] = "FAIL"
        report["fail_reason"] = f"MODEL_TRANSPORT_OR_RUNTIME:{type(exc).__name__}"
        report["error"] = str(exc)[:500]
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["model_name"] = model_name
        write_status(STATUS_FAIL, final_verdict="FAIL", error=report["fail_reason"])
        write_marker("FAIL")
        write_report(report)
        return report

    assert report["qwen_procurement_count"] == 4
    assert QUEUE_GENERATED is False
    assert DOCUMENT_PROCESSING_RUN is False
    # Never call queue producer / AI timer / doc workers
    report["cases"] = case_outputs
    report["case_verdicts"] = case_verdicts
    report["raw_hashes"] = raw_hashes
    final = aggregate_verdict(case_verdicts)
    report["final_verdict"] = final
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["model_name"] = model_name
    report["persist_db_applied"] = False
    report["analytics_refresh"] = False
    report["PERSISTED_RESULTS"] = False
    report["PERSISTENCE_MODE"] = "REPORT_ONLY"

    if persist_db and final == "PASS":
        report["persist_db_skipped_reason"] = "CANARY_REPORT_ONLY_DEFAULT"

    if analytics_refresh and persist_db and final == "PASS":
        report["analytics_refresh"] = False

    write_status(STATUS_PASS if final == "PASS" else STATUS_FAIL, final_verdict=final)
    write_marker(final)
    write_report(report)
    return report
