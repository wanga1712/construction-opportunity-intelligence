"""Cache / refresh engine tests for CRM-V3-LIVE-ANALYTICS-DASHBOARD-1 addendum."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from src.services.v3_analytics_cache import (
    ANALYTICS_CACHE_DIMENSIONS,
    ANALYTICS_CACHE_OWNER,
    ANALYTICS_RUNTIME_DDL,
    FULL_PROCUREMENT_ROWS_CACHED_IN_ANALYTICS,
    InMemoryAnalyticsCache,
)
from src.services.v3_analytics_refresh import (
    ANALYTICS_REFRESH_TIMER_ENABLED,
    ANALYTICS_S7_WRITES,
    ANALYTICS_STALE_AFTER_SEC,
    BACKGROUND_AND_MANUAL_USE_SAME_ENGINE,
    CACHE_ENGINE_REWRITE_AFTER_ROUTING,
    CACHE_ENGINE_REWRITE_AFTER_V3_CUTOVER,
    CONCURRENT_REFRESH_COUNT_MAX,
    HEAVY_ANALYTICS_ON_STREAMLIT_RERUN,
    MANUAL_REFRESH_COOLDOWN_SEC,
    PARTIAL_ANALYTICS_SNAPSHOT_VISIBLE,
    REFRESH_FAILURE_DESTROYS_LAST_GOOD,
    S7_QUERIES_ON_NORMAL_DASHBOARD_LOAD,
    STREAMLIT_MEMORY_CACHE_IS_CANONICAL,
    V3AnalyticsRefreshService,
    read_dashboard,
)
from src.services.v3_analytics_service import V3AnalyticsSnapshot


def _fake_snap(**kwargs) -> V3AnalyticsSnapshot:
    snap = V3AnalyticsSnapshot(
        source_44_open=100,
        source_223_open=20,
        source_44_waiting=2,
        source_223_waiting=1,
        source_open=120,
        source_waiting=3,
        crm_projected=50,
        target_v3_eligible_approx=123,
        not_yet_projected_approx=73,
        pending_routing=50,
        okpd_priors_status="NOT_DEPLOYED",
        title_signals_status="NOT_DEPLOYED",
        candidate_gold=None,
        discovery_required=None,
        level_b_ready=False,
    )
    for k, v in kwargs.items():
        setattr(snap, k, v)
    return snap


def test_invariants_flags():
    assert BACKGROUND_AND_MANUAL_USE_SAME_ENGINE is True
    assert HEAVY_ANALYTICS_ON_STREAMLIT_RERUN is False
    assert S7_QUERIES_ON_NORMAL_DASHBOARD_LOAD == 0
    assert ANALYTICS_S7_WRITES == 0
    assert FULL_PROCUREMENT_ROWS_CACHED_IN_ANALYTICS is False
    assert PARTIAL_ANALYTICS_SNAPSHOT_VISIBLE is False
    assert REFRESH_FAILURE_DESTROYS_LAST_GOOD is False
    assert STREAMLIT_MEMORY_CACHE_IS_CANONICAL is False
    assert CACHE_ENGINE_REWRITE_AFTER_V3_CUTOVER is False
    assert CACHE_ENGINE_REWRITE_AFTER_ROUTING is False
    assert ANALYTICS_RUNTIME_DDL is False
    assert ANALYTICS_REFRESH_TIMER_ENABLED is False
    assert CONCURRENT_REFRESH_COUNT_MAX == 1
    assert MANUAL_REFRESH_COOLDOWN_SEC == 300
    assert ANALYTICS_STALE_AFTER_SEC == 90 * 60
    assert ANALYTICS_CACHE_OWNER == "S13_CRM_DB"
    assert "source_contour" in ANALYTICS_CACHE_DIMENSIONS


def test_background_and_manual_same_engine():
    store = InMemoryAnalyticsCache()
    calls = {"n": 0}

    def compute(tender_db, crm_db, **kwargs):
        calls["n"] += 1
        return _fake_snap()

    held = {"v": False}

    def lock_try():
        if held["v"]:
            return False
        held["v"] = True
        return True

    def lock_release():
        held["v"] = False

    engine = V3AnalyticsRefreshService(
        store,
        lock_try=lock_try,
        lock_release=lock_release,
        compute_fn=compute,
        cooldown_sec=0,
    )
    r1 = engine.refresh_all(trigger="timer")
    r2 = engine.refresh_all(trigger="manual")
    assert r1.ok and r2.ok
    assert calls["n"] == 2
    assert type(engine).refresh_all is V3AnalyticsRefreshService.refresh_all


def test_persisted_cache_and_latest_complete_used():
    store = InMemoryAnalyticsCache()
    engine = V3AnalyticsRefreshService(
        store, compute_fn=lambda *a, **k: _fake_snap(), cooldown_sec=0
    )
    r = engine.refresh_all(trigger="test")
    assert r.ok
    view = read_dashboard(store)
    assert view.ready
    assert view.generation_id == r.generation_id
    assert view.s7_queries == 0
    assert view.data.get("source_44_open") == 100
    assert view.data.get("candidate_gold") is None  # not faked


def test_partial_snapshot_not_visible_and_last_good_survives():
    store = InMemoryAnalyticsCache()
    engine = V3AnalyticsRefreshService(
        store, compute_fn=lambda *a, **k: _fake_snap(crm_projected=11), cooldown_sec=0
    )
    ok = engine.refresh_all(trigger="test")
    assert ok.ok
    good_id = ok.generation_id
    good_projected = read_dashboard(store).data["crm_projected"]

    def boom(*a, **k):
        raise RuntimeError("refresh exploded")

    engine.compute_fn = boom
    bad = engine.refresh_all(trigger="test")
    assert bad.ok is False
    assert bad.status == "FAILED"
    view = read_dashboard(store)
    assert view.generation_id == good_id
    assert view.data["crm_projected"] == good_projected
    # BUILDING/FAILED never current
    latest = store.get_latest_attempt()
    assert latest is not None and latest.status == "FAILED"
    assert latest.is_current is False


def test_concurrent_refresh_max_1():
    store = InMemoryAnalyticsCache()
    held = {"v": False}

    def lock_try():
        if held["v"]:
            return False
        held["v"] = True
        return True

    def lock_release():
        held["v"] = False

    engine = V3AnalyticsRefreshService(
        store,
        lock_try=lock_try,
        lock_release=lock_release,
        compute_fn=lambda *a, **k: _fake_snap(),
        cooldown_sec=0,
    )
    held["v"] = True  # simulate other refresh
    r = engine.refresh_all(trigger="manual")
    assert r.status == "LOCKED"
    assert "уже выполняется" in r.message


def test_manual_refresh_cooldown():
    store = InMemoryAnalyticsCache()
    engine = V3AnalyticsRefreshService(
        store,
        compute_fn=lambda *a, **k: _fake_snap(),
        cooldown_sec=300,
    )
    assert engine.refresh_all(trigger="manual").ok
    again = engine.refresh_all(trigger="manual")
    assert again.status == "COOLDOWN"


def test_manual_refresh_updates_visible_generation():
    store = InMemoryAnalyticsCache()
    n = {"v": 1}

    def compute(*a, **k):
        return _fake_snap(crm_projected=n["v"])

    engine = V3AnalyticsRefreshService(store, compute_fn=compute, cooldown_sec=0)
    r1 = engine.refresh_all(trigger="manual")
    n["v"] = 99
    r2 = engine.refresh_all(trigger="manual")
    assert r2.generation_id != r1.generation_id
    assert read_dashboard(store).data["crm_projected"] == 99


def test_stale_snapshot_warning():
    store = InMemoryAnalyticsCache()
    engine = V3AnalyticsRefreshService(
        store, compute_fn=lambda *a, **k: _fake_snap(), cooldown_sec=0
    )
    engine.refresh_all(trigger="test")
    current = store.get_current_complete()
    assert current is not None
    current.finished_at = datetime.now(timezone.utc) - timedelta(hours=3)
    view = read_dashboard(store, stale_after_sec=90 * 60)
    assert view.stale is True


def test_s7_queries_on_normal_dashboard_load_zero():
    store = InMemoryAnalyticsCache()
    engine = V3AnalyticsRefreshService(
        store, compute_fn=lambda *a, **k: _fake_snap(), cooldown_sec=0
    )
    engine.refresh_all(trigger="test")
    view = read_dashboard(store)
    assert view.s7_queries == S7_QUERIES_ON_NORMAL_DASHBOARD_LOAD == 0


def test_v3_missing_metrics_not_faked_in_cache():
    store = InMemoryAnalyticsCache()
    engine = V3AnalyticsRefreshService(
        store, compute_fn=lambda *a, **k: _fake_snap(), cooldown_sec=0
    )
    engine.refresh_all(trigger="test")
    data = read_dashboard(store).data
    assert data.get("okpd_priors_status") == "NOT_DEPLOYED"
    assert data.get("candidate_gold") is None
    assert data.get("confirmed_status") == "Нет данных подтверждения"


def test_no_full_procurement_rows_in_cache_payload():
    store = InMemoryAnalyticsCache()
    engine = V3AnalyticsRefreshService(
        store, compute_fn=lambda *a, **k: _fake_snap(), cooldown_sec=0
    )
    engine.refresh_all(trigger="test")
    rows = store.load_rows(store.get_current_complete().generation_id)
    blob = str(rows)
    assert "procurement_rows" not in blob
    assert FULL_PROCUREMENT_ROWS_CACHED_IN_ANALYTICS is False


def test_schema_not_ready_blocks_refresh_and_read():
    store = InMemoryAnalyticsCache()
    store.schema_ready = lambda: False  # type: ignore
    engine = V3AnalyticsRefreshService(
        store, compute_fn=lambda *a, **k: _fake_snap(), cooldown_sec=0
    )
    r = engine.refresh_all(trigger="manual")
    assert r.status == "SCHEMA_NOT_READY"
    view = read_dashboard(store)
    assert view.ready is False
    assert view.s7_queries == 0
