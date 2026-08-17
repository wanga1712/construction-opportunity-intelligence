"""Lightweight dashboard read path — persisted snapshot only (no S7)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Protocol

# Keep in sync with v3_analytics_refresh.ANALYTICS_STALE_AFTER_SEC
_DEFAULT_STALE_AFTER_SEC = 90 * 60


class _Store(Protocol):
    def schema_ready(self) -> bool: ...
    def get_current_complete(self): ...
    def get_latest_attempt(self): ...
    def load_dashboard_payload(self, generation_id: int): ...


@dataclass
class DashboardRead:
    ready: bool
    schema_ready: bool
    data: Dict[str, Any]
    generation_id: Optional[int] = None
    data_as_of: Optional[datetime] = None
    last_refresh_status: str = "NONE"
    last_refresh_error: Optional[str] = None
    stale: bool = False
    snapshot_age_sec: Optional[float] = None
    message: str = ""
    s7_queries: int = 0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def read_dashboard(store: _Store, *, stale_after_sec: int = _DEFAULT_STALE_AFTER_SEC) -> DashboardRead:
    """Normal Streamlit load path — snapshot only, zero S7 queries."""
    if not store.schema_ready():
        return DashboardRead(
            ready=False,
            schema_ready=False,
            data={},
            message="Фоновая аналитика ожидает миграцию CRM на S13.",
            s7_queries=0,
        )
    current = store.get_current_complete()
    latest = store.get_latest_attempt()
    if current is None:
        msg = "Нет завершённого снимка аналитики. Нажмите «Обновить данные» после миграции кэша."
        if latest and latest.status == "FAILED":
            msg = f"Нет успешного снимка. Последняя ошибка: {latest.error_summary}"
        return DashboardRead(
            ready=False,
            schema_ready=True,
            data={},
            last_refresh_status=latest.status if latest else "NONE",
            last_refresh_error=latest.error_summary if latest else None,
            message=msg,
            s7_queries=0,
        )

    payload = store.load_dashboard_payload(current.generation_id) or {}
    finished = current.finished_at or current.started_at
    age = None
    stale = False
    if finished is not None:
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=timezone.utc)
        age = (_utcnow() - finished).total_seconds()
        stale = age > stale_after_sec

    last_status = "COMPLETE"
    last_err = None
    if latest and latest.generation_id != current.generation_id and latest.status == "FAILED":
        last_status = "FAILED"
        last_err = latest.error_summary

    return DashboardRead(
        ready=True,
        schema_ready=True,
        data=payload,
        generation_id=current.generation_id,
        data_as_of=finished,
        last_refresh_status=last_status,
        last_refresh_error=last_err,
        stale=stale,
        snapshot_age_sec=age,
        message="",
        s7_queries=0,
    )


def apply_contour_filter_to_payload(data: Dict[str, Any], contour: str) -> Dict[str, Any]:
    """Client-side contour filter from cached Level A fields (no recompute)."""
    if not data or contour in ("ALL", "", None):
        return data
    out = dict(data)
    if contour == "44":
        out["source_open"] = data.get("source_44_open", 0)
        out["source_waiting"] = data.get("source_44_waiting", 0)
        out["awarded_history_excluded"] = data.get("source_44_awarded_all", 0)
        out["target_v3_eligible_approx"] = (
            int(data.get("source_44_open") or 0) + int(data.get("source_44_waiting") or 0)
        )
    elif contour == "223":
        out["source_open"] = data.get("source_223_open", 0)
        out["source_waiting"] = data.get("source_223_waiting", 0)
        out["awarded_history_excluded"] = data.get("source_223_awarded_all", 0)
        out["target_v3_eligible_approx"] = (
            int(data.get("source_223_open") or 0) + int(data.get("source_223_waiting") or 0)
        )
    projected = int(out.get("crm_projected") or 0)
    out["not_yet_projected_approx"] = max(
        0, int(out.get("target_v3_eligible_approx") or 0) - projected
    )
    return out
