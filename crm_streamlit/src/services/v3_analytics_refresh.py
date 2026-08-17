"""Single V3 analytics refresh engine — background timer + manual UI.

Heavy S7/CRM aggregation runs ONLY here. Streamlit reads persisted snapshots.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol

from src.services.v3_analytics_cache import (
    PostgresAnalyticsCache,
    SnapshotRow,
)
from src.services.v3_analytics_service import (
    V3AnalyticsSnapshot,
    load_live_snapshot,
)

ANALYTICS_REFRESH_INTERVAL = "1h"
ANALYTICS_REFRESH_TIMER_ENABLED = False  # canonical CRM cache timer
PRECUTOVER_REFRESH_TIMER_ENABLED = True  # Level-A local file refresh allowed
MANUAL_REFRESH_COOLDOWN_SEC = 300
ANALYTICS_STALE_AFTER_SEC = 90 * 60
CONCURRENT_REFRESH_COUNT_MAX = 1
ANALYTICS_S7_WRITES = 0
HEAVY_ANALYTICS_ON_STREAMLIT_RERUN = False
S7_QUERIES_ON_NORMAL_DASHBOARD_LOAD = 0
BACKGROUND_AND_MANUAL_USE_SAME_ENGINE = True
CACHE_ENGINE_REWRITE_AFTER_V3_CUTOVER = False
CACHE_ENGINE_REWRITE_AFTER_ROUTING = False
PARTIAL_ANALYTICS_SNAPSHOT_VISIBLE = False
REFRESH_FAILURE_DESTROYS_LAST_GOOD = False
STREAMLIT_MEMORY_CACHE_IS_CANONICAL = False
DASHBOARD_STRUCTURE_VISIBLE_WITHOUT_V3_SCHEMA = True

# CRM advisory lock key (distinct from AI runner locks)
ANALYTICS_REFRESH_LOCK_ID = 71330001


class CacheStore(Protocol):
    def schema_ready(self) -> bool: ...
    def start_generation(self, trigger: str = "manual"): ...
    def write_rows(self, generation_id: int, rows) -> int: ...
    def complete_generation(self, generation_id: int, **kwargs): ...
    def fail_generation(self, generation_id: int, error: str, **kwargs): ...
    def get_current_complete(self): ...
    def get_latest_attempt(self): ...
    def load_dashboard_payload(self, generation_id: int): ...


@dataclass
class RefreshResult:
    ok: bool
    status: str  # COMPLETE | FAILED | LOCKED | COOLDOWN | SCHEMA_NOT_READY
    message: str
    generation_id: Optional[int] = None
    duration_ms: Optional[int] = None
    source_query_ms: Optional[int] = None
    crm_query_ms: Optional[int] = None
    cache_write_ms: Optional[int] = None
    last_good_generation_id: Optional[int] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _snapshot_to_rows(
    snap: V3AnalyticsSnapshot,
    *,
    okpd_payload: Optional[Dict[str, Any]] = None,
    subcategory_registry: Optional[List[Dict[str, Any]]] = None,
) -> list[SnapshotRow]:
    now = _utcnow()
    d = snap.to_dict()
    if okpd_payload is not None:
        d["okpd_funnel"] = okpd_payload
    if subcategory_registry is not None:
        d["subcategory_registry"] = subcategory_registry
    rows: list[SnapshotRow] = [
        SnapshotRow(
            snapshot_key="global",
            metric_group="DASHBOARD",
            metric_name="snapshot",
            metric_value=None,
            payload_json=d,
            data_as_of=now,
        ),
        SnapshotRow(
            snapshot_key="global",
            metric_group="SOURCE_FUNNEL",
            metric_name="summary",
            payload_json={
                "source_44_open": snap.source_44_open,
                "source_223_open": snap.source_223_open,
                "source_44_waiting": snap.source_44_waiting,
                "source_223_waiting": snap.source_223_waiting,
                "source_open": snap.source_open,
                "source_waiting": snap.source_waiting,
                "awarded_history_excluded": snap.awarded_history_excluded,
                "target_v3_eligible_approx": snap.target_v3_eligible_approx,
            },
            metric_value=float(snap.source_open),
            data_as_of=now,
        ),
        SnapshotRow(
            snapshot_key="global",
            metric_group="PROJECTION_FUNNEL",
            metric_name="summary",
            payload_json={
                "crm_projected": snap.crm_projected,
                "not_yet_projected_approx": snap.not_yet_projected_approx,
                "pending_routing": snap.pending_routing,
                "routed_procurements": snap.routed_procurements,
                "procurements_with_opportunities": snap.procurements_with_opportunities,
                "total_opportunities": snap.total_opportunities,
                "active_leads": snap.active_leads,
            },
            metric_value=float(snap.crm_projected),
            data_as_of=now,
        ),
    ]
    if okpd_payload is not None:
        rows.append(
            SnapshotRow(
                snapshot_key="global",
                metric_group="OKPD_FUNNEL",
                metric_name="summary",
                payload_json=okpd_payload,
                metric_value=float((okpd_payload.get("meta") or {}).get("okpd_group_count") or 0),
                data_as_of=now,
            )
        )
    if subcategory_registry is not None:
        rows.append(
            SnapshotRow(
                snapshot_key="global",
                metric_group="SUBCATEGORIES",
                metric_name="registry",
                payload_json={"rows": subcategory_registry},
                data_as_of=now,
            )
        )
    # Keep remaining legacy groups compact
    rows.extend(
        [
            SnapshotRow(
                snapshot_key="global",
                metric_group="OKPD",
                metric_name="summary",
                payload_json={
                    "status": snap.okpd_priors_status,
                    "crm_okpd_nonnull": snap.crm_okpd_nonnull,
                    "crm_okpd_null": snap.crm_okpd_null,
                },
                data_as_of=now,
            ),
            SnapshotRow(
                snapshot_key="global",
                metric_group="CANDIDATE_MEDALS",
                metric_name="summary",
                payload_json={
                    "gold": snap.candidate_gold,
                    "silver": snap.candidate_silver,
                    "bronze": snap.candidate_bronze,
                    "wood": snap.candidate_wood,
                },
                data_as_of=now,
            ),
            SnapshotRow(
                snapshot_key="global",
                metric_group="VERSIONS",
                metric_name="summary",
                payload_json=dict(snap.versions),
                data_as_of=now,
            ),
            SnapshotRow(
                snapshot_key="global",
                metric_group="CONFIRMED_MEDALS",
                metric_name="summary",
                payload_json={
                    "status": snap.confirmed_status,
                    "medals": snap.confirmed_medals,
                },
                data_as_of=now,
            ),
        ]
    )
    return rows


class V3AnalyticsRefreshService:
    """One engine for timer + manual refresh."""

    def __init__(
        self,
        store: CacheStore,
        *,
        tender_db=None,
        crm_db=None,
        lock_try: Optional[Callable[[], bool]] = None,
        lock_release: Optional[Callable[[], None]] = None,
        cooldown_sec: int = MANUAL_REFRESH_COOLDOWN_SEC,
        compute_fn: Optional[Callable[..., V3AnalyticsSnapshot]] = None,
    ) -> None:
        self.store = store
        self.tender_db = tender_db
        self.crm_db = crm_db
        self._lock_try = lock_try or (lambda: True)
        self._lock_release = lock_release or (lambda: None)
        self.cooldown_sec = cooldown_sec
        self.compute_fn = compute_fn or load_live_snapshot
        self._last_manual_at: Optional[datetime] = None

    def refresh_all(self, *, trigger: str = "manual") -> RefreshResult:
        last_good = self.store.get_current_complete()
        last_good_id = last_good.generation_id if last_good else None

        if not self.store.schema_ready():
            return RefreshResult(
                ok=False,
                status="SCHEMA_NOT_READY",
                message="Фоновая аналитика ожидает миграцию CRM на S13.",
                last_good_generation_id=last_good_id,
            )

        if trigger == "manual" and self._last_manual_at is not None:
            age = (_utcnow() - self._last_manual_at).total_seconds()
            if age < self.cooldown_sec:
                left = int(self.cooldown_sec - age)
                return RefreshResult(
                    ok=False,
                    status="COOLDOWN",
                    message=f"Повторное обновление через {left} с.",
                    last_good_generation_id=last_good_id,
                )

        if not self._lock_try():
            return RefreshResult(
                ok=False,
                status="LOCKED",
                message="Обновление уже выполняется.",
                last_good_generation_id=last_good_id,
            )

        t_all = time.perf_counter()
        gen = None
        try:
            gen = self.store.start_generation(trigger=trigger)
            # BUILDING generation is never exposed as current
            t_src = time.perf_counter()
            snap = self.compute_fn(self.tender_db, self.crm_db, contour="ALL")
            from src.services.v3_analytics_okpd import (
                build_okpd_funnel_level_a,
                load_category_subcategory_registry,
                okpd_rows_to_payload,
            )

            okpd_rows, okpd_meta = build_okpd_funnel_level_a(
                self.tender_db, self.crm_db
            )
            okpd_payload = okpd_rows_to_payload(okpd_rows, okpd_meta)
            registry = load_category_subcategory_registry(self.crm_db)
            source_ms = int((time.perf_counter() - t_src) * 1000)
            # CRM portion already inside compute; approximate split
            crm_ms = source_ms // 3
            source_ms = source_ms - crm_ms

            t_wrt = time.perf_counter()
            rows = _snapshot_to_rows(
                snap,
                okpd_payload=okpd_payload,
                subcategory_registry=registry,
            )
            n = self.store.write_rows(gen.generation_id, rows)
            write_ms = int((time.perf_counter() - t_wrt) * 1000)

            versions = snap.versions or {}
            dur = int((time.perf_counter() - t_all) * 1000)
            completed = self.store.complete_generation(
                gen.generation_id,
                duration_ms=dur,
                source_query_ms=source_ms,
                crm_query_ms=crm_ms,
                cache_write_ms=write_ms,
                routing_version=str(versions.get("routing_version") or ""),
                registry_version=str(versions.get("registry_version") or ""),
                registry_hash=str(versions.get("registry_hash") or ""),
                metrics_collected=n,
            )
            if trigger == "manual":
                self._last_manual_at = _utcnow()
            return RefreshResult(
                ok=True,
                status="COMPLETE",
                message="Обновление завершено.",
                generation_id=completed.generation_id,
                duration_ms=dur,
                source_query_ms=source_ms,
                crm_query_ms=crm_ms,
                cache_write_ms=write_ms,
                last_good_generation_id=completed.generation_id,
            )
        except Exception as exc:
            dur = int((time.perf_counter() - t_all) * 1000)
            if gen is not None:
                self.store.fail_generation(gen.generation_id, str(exc), duration_ms=dur)
            # Previous COMPLETE remains current
            still = self.store.get_current_complete()
            return RefreshResult(
                ok=False,
                status="FAILED",
                message=f"Ошибка обновления: {exc}",
                generation_id=gen.generation_id if gen else None,
                duration_ms=dur,
                last_good_generation_id=still.generation_id if still else last_good_id,
            )
        finally:
            try:
                self._lock_release()
            except Exception:
                pass


def make_pg_lock_pair(crm_db, lock_id: int = ANALYTICS_REFRESH_LOCK_ID):
    """PostgreSQL advisory lock helpers (session-level)."""

    def _try() -> bool:
        try:
            rows = crm_db.execute_query(
                "SELECT pg_try_advisory_lock(%(id)s) AS ok", {"id": lock_id}
            )
            row = rows[0]
            return bool(row.get("ok") if isinstance(row, dict) else row[0])
        except Exception:
            return False

    def _release() -> None:
        try:
            crm_db.execute_query(
                "SELECT pg_advisory_unlock(%(id)s) AS ok", {"id": lock_id}
            )
        except Exception:
            pass

    return _try, _release


def build_refresh_service(
    tender_db,
    crm_db,
    *,
    store: Optional[CacheStore] = None,
    force_precutover: bool = False,
) -> V3AnalyticsRefreshService:
    from src.services.v3_analytics_precutover import (
        PreCutoverFileCache,
        make_file_lock_pair,
        resolve_analytics_store,
    )

    if store is None:
        store, _kind = resolve_analytics_store(crm_db, force_precutover=force_precutover)
        if isinstance(store, PostgresAnalyticsCache) and crm_db is not None:
            lock_try, lock_release = make_pg_lock_pair(crm_db)
        elif isinstance(store, PreCutoverFileCache):
            lock_try, lock_release = make_file_lock_pair(store.root)
        else:
            held = {"v": False}

            def lock_try() -> bool:
                if held["v"]:
                    return False
                held["v"] = True
                return True

            def lock_release() -> None:
                held["v"] = False
    else:
        lock_try, lock_release = (lambda: True), (lambda: None)
        if crm_db is not None and isinstance(store, PostgresAnalyticsCache):
            lock_try, lock_release = make_pg_lock_pair(crm_db)
        elif isinstance(store, PreCutoverFileCache):
            lock_try, lock_release = make_file_lock_pair(store.root)

    return V3AnalyticsRefreshService(
        store,
        tender_db=tender_db,
        crm_db=crm_db,
        lock_try=lock_try,
        lock_release=lock_release,
    )


# Re-exports for callers/tests
from src.services.v3_analytics_read import (  # noqa: E402
    DashboardRead,
    apply_contour_filter_to_payload,
    read_dashboard,
)
