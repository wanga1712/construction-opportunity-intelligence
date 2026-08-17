"""Operational backlog-drain / steady-state scheduling helpers. No semantics."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("commercial_routing_v3.routing_drain")

STATUS_PATH = Path("/var/lib/crm-v3-canary/continuous_backlog_drain/routing_status.json")
DEFAULT_BATCH_SIZE = 100
DEFAULT_MAX_RUNTIME_SEC = 3600


def write_routing_status(payload: Dict[str, Any], *, path: Optional[Path] = None) -> None:
    out = path or STATUS_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    data = dict(payload)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(out)


def run_backlog_drain(
    *,
    tender_db,
    crm_db,
    run_live_fn,
    fetch_candidates_fn,
    classify_fn,
    allocate_fn,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_runtime_sec: int = DEFAULT_MAX_RUNTIME_SEC,
) -> Dict[str, Any]:
    """Process bounded batches until eligible backlog empty or max runtime.

    One failed item inside run_live must not abort the drain loop.
    """
    started = time.monotonic()
    totals = {"success": 0, "failed": 0, "batches": 0, "qwen_inference_count": 0}
    mode = "STEADY_STATE"
    last_ids: list = []
    stop_reason = "empty"

    from src.services.commercial_routing_v3.decision_authorities import (
        qwen_candidate_inference_enabled,
    )

    if not qwen_candidate_inference_enabled():
        write_routing_status(
            {
                "ROUTING_MODE": "FROZEN",
                "stop_reason": "MODEL_V0_CALIBRATION_FREEZE",
                "totals": totals,
            }
        )
        logger.warning("MODEL_V0 freeze: backlog drain will not call Qwen")
        return {"success": 0, "failed": 0, "batches": 0, "frozen": True}

    while True:
        elapsed = time.monotonic() - started
        if elapsed >= max_runtime_sec:
            stop_reason = "max_runtime"
            break

        candidates = fetch_candidates_fn(tender_db, crm_db)
        backlog = classify_fn(candidates)
        eligible = int(backlog.get("TOTAL_ROUTING_ELIGIBLE_BACKLOG") or 0)
        try:
            from src.services.commercial_routing_v3.gpu_arbiter import set_queue_depths

            set_queue_depths(routing=eligible, document=int(backlog.get("DOCUMENT_QUEUE_DEPTH") or 0))
        except Exception:
            pass
        if eligible <= 0:
            mode = "STEADY_STATE"
            stop_reason = "empty"
            write_routing_status(
                {
                    "ROUTING_MODE": mode,
                    "TOTAL_ELIGIBLE_BACKLOG": 0,
                    "ACTIVE_BACKLOG": 0,
                    "AWARDED_BACKLOG": 0,
                    "CURRENT_BATCH_SIZE": 0,
                    "CURRENT_PROCUREMENT_ID": None,
                    "LAST_INFERENCE_AT": None,
                    "LAST_COMPLETED_AT": datetime.now(timezone.utc).isoformat(),
                    "stop_reason": stop_reason,
                    "totals": totals,
                    "backlog": backlog,
                }
            )
            break

        mode = "BACKLOG_DRAIN"
        batch = allocate_fn(candidates, total=batch_size)
        if not batch:
            stop_reason = "empty_after_allocate"
            break

        write_routing_status(
            {
                "ROUTING_MODE": mode,
                "TOTAL_ELIGIBLE_BACKLOG": eligible,
                "ACTIVE_BACKLOG": backlog.get("ACTIVE_BACKLOG"),
                "AWARDED_BACKLOG": backlog.get("AWARDED_BACKLOG"),
                "CURRENT_BATCH_SIZE": len(batch),
                "CURRENT_PROCUREMENT_ID": batch[0].get("id"),
                "LAST_INFERENCE_AT": datetime.now(timezone.utc).isoformat(),
                "batch_ids": [c.get("id") for c in batch],
                "totals": totals,
                "backlog": backlog,
                "elapsed_sec": round(elapsed, 1),
                "max_runtime_sec": max_runtime_sec,
            }
        )

        logger.info(
            "DRAIN batch=%s eligible=%s active=%s awarded=%s elapsed=%.0fs",
            len(batch),
            eligible,
            backlog.get("ACTIVE_BACKLOG"),
            backlog.get("AWARDED_BACKLOG"),
            elapsed,
        )

        # Process exactly this batch by temporarily filtering via run_live limit
        # on already capacity-selected IDs: call process path through run_live
        # with full selector — re-fetch is intentional so NEW work gets priority.
        result = run_live_fn(tender_db, crm_db, limit=batch_size)
        totals["success"] += int(result.get("success") or 0)
        totals["failed"] += int(result.get("failed") or 0)
        totals["batches"] += 1
        totals["qwen_inference_count"] += int(result.get("success") or 0) + int(
            result.get("failed") or 0
        )
        last_ids = [c.get("id") for c in batch]
        write_routing_status(
            {
                "ROUTING_MODE": mode,
                "TOTAL_ELIGIBLE_BACKLOG": eligible,
                "ACTIVE_BACKLOG": backlog.get("ACTIVE_BACKLOG"),
                "AWARDED_BACKLOG": backlog.get("AWARDED_BACKLOG"),
                "CURRENT_BATCH_SIZE": len(batch),
                "CURRENT_PROCUREMENT_ID": None,
                "LAST_COMPLETED_AT": datetime.now(timezone.utc).isoformat(),
                "last_batch_result": result,
                "last_batch_ids": last_ids,
                "totals": totals,
                "elapsed_sec": round(time.monotonic() - started, 1),
                "max_runtime_sec": max_runtime_sec,
            }
        )

        # If batch made no progress, avoid tight infinite loop on permanent failures
        if int(result.get("success") or 0) == 0 and int(result.get("failed") or 0) == 0:
            stop_reason = "zero_progress"
            break

    final = {
        "ROUTING_MODE": mode if stop_reason != "empty" else "STEADY_STATE",
        "stop_reason": stop_reason,
        "totals": totals,
        "elapsed_sec": round(time.monotonic() - started, 1),
        "max_runtime_sec": max_runtime_sec,
        "batch_size": batch_size,
    }
    write_routing_status(final)
    logger.info("DRAIN finished: %s", final)
    return final
