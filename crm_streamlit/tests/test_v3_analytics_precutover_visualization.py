"""Corrective visualization + pre-cutover Level-A cache tests."""
from __future__ import annotations

import ast
from pathlib import Path

from src.services.v3_analytics_metric_state import (
    MetricState,
    confirmed_metric_state,
    metric_display,
    routing_metric_state,
)
from src.services.v3_analytics_precutover import (
    CANONICAL_CACHE_PRIORITY,
    PRECUTOVER_ANALYTICS_CRM_WRITES,
    PRECUTOVER_ANALYTICS_S7_WRITES,
    PRECUTOVER_CACHE_PRIORITY,
    PRECUTOVER_CACHE_REMOVAL_REQUIRES_UI_REWRITE,
    PreCutoverFileCache,
    load_prepared_configuration,
    resolve_analytics_store,
)
from src.services.v3_analytics_refresh import (
    DASHBOARD_STRUCTURE_VISIBLE_WITHOUT_V3_SCHEMA,
    V3AnalyticsRefreshService,
    read_dashboard,
)
from src.services.v3_analytics_service import V3AnalyticsSnapshot
from src.ui import v3_analytics_page_sections as sections

ROOT = Path(__file__).resolve().parents[1]


def _snap(**kwargs) -> V3AnalyticsSnapshot:
    s = V3AnalyticsSnapshot(
        source_44_open=11601,
        source_223_open=1559,
        source_44_waiting=3,
        source_223_waiting=13,
        source_open=13160,
        source_waiting=16,
        awarded_history_excluded=56612,
        crm_projected=1175,
        target_v3_eligible_approx=13176,
        not_yet_projected_approx=12001,
        level_b_ready=False,
        candidate_gold=None,
        okpd_priors_status="NOT_DEPLOYED",
    )
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


def test_dashboard_structure_flag():
    assert DASHBOARD_STRUCTURE_VISIBLE_WITHOUT_V3_SCHEMA is True


def test_page_without_v3_schema_is_fully_rendered_helpers_exist():
    # Structure helpers always callable with empty/Level-A data (no early hide)
    names = {
        "render_top_kpis",
        "render_funnel",
        "render_source_44_223",
        "render_projection_block",
        "render_prepared_config",
        "render_scenario_cards",
        "render_category_table",
        "render_medal_blocks",
        "render_lifecycle_discovery_quality",
    }
    for n in names:
        assert hasattr(sections, n)
    # Page module must not early-return on missing schema (AST check)
    tree = ast.parse((ROOT / "src/ui/v3_analytics_page.py").read_text(encoding="utf-8"))
    src = (ROOT / "src/ui/v3_analytics_page.py").read_text(encoding="utf-8")
    assert "ожидает миграцию CRM на S13" not in src or "render_infra_banner" in src
    assert "render_okpd_funnel_table" in src and "render_compact_kpis" in src
    assert "return" in src  # still has returns in helpers
    # No early empty-page return after missing schema_ready
    assert "if not view.get(\"schema_ready\"):\n        st.warning" not in src


def test_not_started_and_not_available_not_zeroed():
    text, state = metric_display(None, MetricState.NOT_STARTED)
    assert state == MetricState.NOT_STARTED
    assert "0" != text
    assert "—" in text
    text2, state2 = metric_display(None, MetricState.NOT_AVAILABLE)
    assert state2 == MetricState.NOT_AVAILABLE
    assert text2.startswith("—")
    assert routing_metric_state(False, False) == MetricState.NOT_STARTED
    assert confirmed_metric_state(False) == MetricState.NOT_AVAILABLE


def test_level_a_precutover_refresh_readonly(tmp_path):
    store = PreCutoverFileCache(root=tmp_path)
    engine = V3AnalyticsRefreshService(
        store,
        compute_fn=lambda *a, **k: _snap(),
        cooldown_sec=0,
    )
    r = engine.refresh_all(trigger="manual")
    assert r.ok
    assert store.s7_writes == PRECUTOVER_ANALYTICS_S7_WRITES == 0
    assert store.crm_writes == PRECUTOVER_ANALYTICS_CRM_WRITES == 0
    view = read_dashboard(store)
    assert view.ready
    assert view.data.get("source_44_open") == 11601
    assert view.data.get("crm_projected") == 1175
    assert view.data.get("candidate_gold") is None
    assert view.s7_queries == 0


def test_manual_level_a_refresh_works(tmp_path):
    store = PreCutoverFileCache(root=tmp_path)
    n = {"v": 10}

    def compute(*a, **k):
        return _snap(crm_projected=n["v"])

    engine = V3AnalyticsRefreshService(store, compute_fn=compute, cooldown_sec=0)
    assert engine.refresh_all(trigger="manual").ok
    n["v"] = 99
    assert engine.refresh_all(trigger="manual").ok
    assert read_dashboard(store).data["crm_projected"] == 99


def test_precutover_to_canonical_cache_switch(monkeypatch, tmp_path):
    store, kind = resolve_analytics_store(None, force_precutover=True)
    assert kind == "PRECUTOVER_FILE"
    assert CANONICAL_CACHE_PRIORITY == "S13_CRM"
    assert PRECUTOVER_CACHE_PRIORITY == "FALLBACK"
    assert PRECUTOVER_CACHE_REMOVAL_REQUIRES_UI_REWRITE is False

    class FakeDb:
        pass

    monkeypatch.setattr(
        "src.services.v3_analytics_precutover.cache_schema_ready", lambda _db: True
    )
    store2, kind2 = resolve_analytics_store(FakeDb(), force_precutover=False)
    assert kind2 == "CANONICAL_S13_CRM"
    assert store2.__class__.__name__ == "PostgresAnalyticsCache"


def test_prepared_configuration_from_report():
    prep = load_prepared_configuration(ROOT)
    assert prep.get("okpd_priors_prepared") == 334
    assert prep.get("legacy_soft_negatives") == 777
    assert "concrete_repair_materials" in (prep.get("categories_without_priors") or [])
    assert int(prep.get("categories_with_priors") or 0) >= 1


def test_funnel_category_scenario_medal_contract_semantics():
    disp = metric_display(None, MetricState.NOT_STARTED)[0]
    assert disp != "0"
    assert "—" in disp
    conf = metric_display(None, MetricState.NOT_AVAILABLE)[0]
    assert conf != "0"
    assert "—" in conf
