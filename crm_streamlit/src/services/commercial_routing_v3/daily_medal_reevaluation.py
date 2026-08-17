"""Deterministic daily medal reevaluation. No Qwen. Dry-run by default."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from src.services.commercial_routing_v3.candidate_scoring import CANDIDATE_SCORING_VERSION
from src.services.commercial_routing_v3.medal_lineage import (
    REASON_ACTIVE_DECAY,
    REASON_AWARDED_DECAY,
    REASON_OPEN_TO_AWARDED,
    REASON_SOURCE_CHANGE,
    lineage_from_mapping,
    recalculate_current_effective_priority,
    scoring_ctx_from_timing,
)
from src.services.commercial_routing_v3.post_award_execution_timing import (
    clock_from_model_input,
)

PROPOSED_PRODUCTION_CADENCE = (
    "Minimum daily 06:00 Europe/Moscow after overnight source projection. "
    "Inexpensive deterministic pass may run hourly alongside crm-procurement-sync "
    "if that timer is active. Qwen is never part of this job. Timer NOT enabled in this WIP."
)
DAILY_REEVALUATION_VERSION = "v1_time_only_20260814"


def decay_reason_for_lifecycle(lifecycle: str, *, previous_lifecycle: Optional[str] = None) -> str:
    lc = str(lifecycle or "").upper()
    prev = str(previous_lifecycle or "").upper()
    if prev == "OPEN" and lc == "AWARDED":
        return REASON_OPEN_TO_AWARDED
    if lc == "AWARDED":
        return REASON_AWARDED_DECAY
    return REASON_ACTIVE_DECAY


def reevaluate_opportunity(
    row: Dict[str, Any],
    *,
    as_of: Optional[date] = None,
    now: Optional[datetime] = None,
    source_data_changed: bool = False,
    previous_lifecycle: Optional[str] = None,
) -> Dict[str, Any]:
    """Rescore current effective medal from frozen semantics + clocks. qwen_calls=0."""
    as_of = as_of or datetime.now(timezone.utc).date()
    lineage = lineage_from_mapping(row)
    if not lineage.semantic_hypothesis.get("category_code"):
        return {
            "lineage": lineage.as_dict(),
            "history": None,
            "qwen_calls": 0,
            "skipped": True,
            "reason": "no_frozen_semantic_hypothesis",
        }
    lc = str(row.get("normalized_lifecycle") or row.get("lifecycle") or "OPEN").upper()
    mi = row.get("model_input") if isinstance(row.get("model_input"), dict) else {}
    clock = None
    if lc == "AWARDED":
        clock = clock_from_model_input(mi or row, as_of=as_of)
    reason = decay_reason_for_lifecycle(lc, previous_lifecycle=previous_lifecycle)
    if source_data_changed:
        reason = REASON_SOURCE_CHANGE
    ctx = scoring_ctx_from_timing(
        procurement_form=str(row.get("procurement_form") or "UNKNOWN"),
        routing_mode=row.get("routing_mode"),
        lifecycle=lc,
        object_classification=row.get("object_classification"),
        commercial_timing_value=row.get("commercial_timing_value")
        if row.get("commercial_timing_value") is not None
        else mi.get("commercial_timing_value"),
        remaining_days=row.get("remaining_days")
        if row.get("remaining_days") is not None
        else mi.get("remaining_days"),
        execution_clock=clock,
        source_origin=row.get("source_origin") or mi.get("source_origin"),
        source_data_quality=str(row.get("source_data_quality") or "OK"),
        initial_price=float(row.get("initial_price") or mi.get("initial_price") or 0.0),
        final_contract_price=(
            float(row["final_contract_price"])
            if row.get("final_contract_price") not in (None, "")
            else None
        ),
    )
    lineage, history, qwen_calls = recalculate_current_effective_priority(
        lineage,
        ctx,
        reason=reason,
        procurement_id=row.get("procurement_id"),
        now=now,
        as_of=as_of,
    )
    return {
        "lineage": lineage.as_dict(),
        "history": history,
        "qwen_calls": qwen_calls,
        "skipped": False,
        "reason": reason,
        "scoring_version": CANDIDATE_SCORING_VERSION,
        "daily_reevaluation_version": DAILY_REEVALUATION_VERSION,
    }


def reevaluate_many(
    rows: List[Dict[str, Any]],
    *,
    as_of: Optional[date] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    histories: List[Dict[str, Any]] = []
    qwen = 0
    updated = 0
    for row in rows:
        out = reevaluate_opportunity(row, as_of=as_of, now=now)
        qwen += int(out.get("qwen_calls") or 0)
        if out.get("history"):
            histories.append(out["history"])
            updated += 1
            row.update(out["lineage"])
            row["candidate_medal"] = out["lineage"].get("current_effective_medal")
        elif not out.get("skipped"):
            row.update(out["lineage"])
    return {
        "qwen_calls": qwen,
        "history_rows": histories,
        "updated": updated,
        "evaluated": len(rows),
        "proposed_cadence": PROPOSED_PRODUCTION_CADENCE,
    }
