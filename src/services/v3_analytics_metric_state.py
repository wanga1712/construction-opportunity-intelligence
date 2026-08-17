"""Metric display states for V3 analytics UI (VALUE / NOT_STARTED / NOT_AVAILABLE)."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional, Tuple


class MetricState(str, Enum):
    VALUE = "VALUE"
    NOT_STARTED = "NOT_STARTED"
    NOT_AVAILABLE = "NOT_AVAILABLE"


def metric_display(
    value: Any,
    state: MetricState,
    *,
    not_started_hint: str = "Ожидает routing",
    not_available_hint: str = "Ожидает documents",
) -> Tuple[str, MetricState]:
    """Return (display_text, state). Never coerce NOT_* into numeric 0."""
    if state == MetricState.VALUE:
        if value is None:
            return "—", MetricState.VALUE
        return str(value), MetricState.VALUE
    if state == MetricState.NOT_STARTED:
        return f"— · {not_started_hint}", state
    return f"— · {not_available_hint}", state


def routing_metric_state(level_b_ready: bool, has_routing_data: bool) -> MetricState:
    if level_b_ready and has_routing_data:
        return MetricState.VALUE
    return MetricState.NOT_STARTED


def confirmed_metric_state(level_c_ready: bool) -> MetricState:
    if level_c_ready:
        return MetricState.VALUE
    return MetricState.NOT_AVAILABLE


STATUS_BADGE = {
    "LIVE": "LIVE",
    "PREPARED": "PREPARED",
    "NOT_DEPLOYED": "NOT DEPLOYED",
    "NOT_STARTED": "NOT STARTED",
    "PENDING_DOCS": "PENDING DOCS",
    "STALE": "STALE",
    "ERROR": "ERROR",
}


def medal_text(medal: str, *, confirmed: bool = False) -> str:
    m = (medal or "").upper()
    return f"{m} · CONFIRMED" if confirmed else f"{m} · CANDIDATE"
