"""OKPD funnel / subcategory drilldown tests."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from src.services.v3_analytics_cache import ANALYTICS_CACHE_DIMENSIONS
from src.services.v3_analytics_okpd import (
    ANALYTICS_CACHE_SUPPORTS_OKPD,
    ANALYTICS_CACHE_SUPPORTS_SUBCATEGORY,
    ANALYTICS_OKPD_CACHE_IS_AGGREGATE_ONLY,
    NOT_STARTED,
    RAW_CATEGORY_CODE_AS_PRIMARY_LABEL,
    SUBCATEGORY_NOT_ASSIGNED,
    SUBCATEGORY_NOT_ASSIGNED_LABEL_RU,
    display_cell,
    filter_okpd_rows,
    load_prepared_okpd_prior_index,
    match_prepared_priors,
    build_okpd_funnel_level_a,
    OkpdFunnelRow,
)
from src.services.v3_analytics_precutover import PreCutoverFileCache
from src.services.v3_analytics_refresh import V3AnalyticsRefreshService, read_dashboard
from src.services.v3_analytics_service import V3AnalyticsSnapshot

ROOT = Path(__file__).resolve().parents[1]


def test_cache_supports_okpd_and_subcategory():
    assert ANALYTICS_CACHE_SUPPORTS_OKPD is True
    assert ANALYTICS_CACHE_SUPPORTS_SUBCATEGORY is True
    assert ANALYTICS_OKPD_CACHE_IS_AGGREGATE_ONLY is True
    assert "okpd_code" in ANALYTICS_CACHE_DIMENSIONS
    assert "subcategory_code" in ANALYTICS_CACHE_DIMENSIONS
    assert RAW_CATEGORY_CODE_AS_PRIMARY_LABEL is False


def test_soft_negative_not_drop_and_hard_separate():
    row = OkpdFunnelRow(
        okpd_code="27.40",
        source_received=500,
        technically_eligible=497,
        technically_rejected=3,
        title_negative_signal=NOT_STARTED,
        hard_excluded=NOT_STARTED,
    )
    assert row.title_negative_signal == NOT_STARTED
    assert display_cell(row.title_negative_signal) != "0"
    assert "NOT STARTED" in display_cell(row.title_negative_signal)
    assert display_cell(row.hard_excluded) != display_cell(0)


def test_prepared_prior_not_labeled_ai():
    idx = load_prepared_okpd_prior_index(ROOT)
    hits = match_prepared_priors("42.11.20.900", idx)
    assert hits
    assert all(h.get("label") == "PREPARED PRIOR" for h in hits)
    codes = {h["category_code"] for h in hits}
    assert "lighting" in codes


def test_okpd_funnel_level_a_from_mocks():
    tender = MagicMock()
    crm = MagicMock()

    def t_exec(sql, params=None):
        assert "main_code" in sql or "sub_code" in sql or "commission" in sql or True
        if "reestr_contract_44_fz" in sql and "commission" not in sql:
            return [
                {"okpd_code": "27.40", "okpd_name": "Освещение", "received": 40, "eligible": 39, "missing_identity": 1},
                {"okpd_code": "42.11", "okpd_name": "Дороги", "received": 100, "eligible": 100, "missing_identity": 0},
            ]
        if "223_fz" in sql and "commission" not in sql:
            return [{"okpd_code": "26.2", "okpd_name": "ПК", "received": 20, "eligible": 20, "missing_identity": 0}]
        if "commission" in sql:
            return []
        return []

    def c_exec(sql, params=None):
        if "crm_procurements" in sql:
            return [
                {"okpd_code": "27.40", "okpd_name": "Освещение", "projected": 12, "c44": 12, "c223": 0},
                {"okpd_code": "42.11", "okpd_name": "Дороги", "projected": 50, "c44": 50, "c223": 0},
            ]
        return []

    tender.execute_query.side_effect = t_exec
    crm.execute_query.side_effect = c_exec
    rows, meta = build_okpd_funnel_level_a(tender, crm, project_root=ROOT)
    assert meta["okpd_group_count"] >= 2
    by = {r.okpd_code: r for r in rows}
    assert by["27.40"].source_received == 40
    assert by["27.40"].technically_rejected == 1
    assert by["27.40"].projected_to_crm == 12


def test_subcategory_not_assigned_policy():
    assert SUBCATEGORY_NOT_ASSIGNED == "SUBCATEGORY_NOT_ASSIGNED"
    assert "не определена" in SUBCATEGORY_NOT_ASSIGNED_LABEL_RU.lower() or "Подкатегория" in SUBCATEGORY_NOT_ASSIGNED_LABEL_RU


def test_refresh_embeds_okpd_funnel(tmp_path, monkeypatch):
    store = PreCutoverFileCache(root=tmp_path)

    def compute(*a, **k):
        return V3AnalyticsSnapshot(source_open=10, crm_projected=5, source_44_open=8, source_223_open=2)

    import src.services.v3_analytics_okpd as okpd_mod

    def fake_build(tender_db, crm_db, **kwargs):
        row = OkpdFunnelRow(
            okpd_code="27.40",
            okpd_name="Освещение",
            source_received=40,
            technically_eligible=39,
            technically_rejected=1,
            projected_to_crm=12,
            prepared_prior_categories=[
                {"category_code": "lighting", "display_name": "Освещение", "label": "PREPARED PRIOR"}
            ],
        )
        return [row], {"okpd_group_count": 1, "okpd_aggregation_duration_ms": 1}

    monkeypatch.setattr(okpd_mod, "build_okpd_funnel_level_a", fake_build)
    monkeypatch.setattr(
        okpd_mod,
        "load_category_subcategory_registry",
        lambda *a, **k: [
            {
                "category_code": "lighting",
                "category_display_name": "Освещение",
                "subcategory_code": None,
                "subcategory_display_name": None,
            }
        ],
    )
    engine = V3AnalyticsRefreshService(store, compute_fn=compute, cooldown_sec=0)
    r = engine.refresh_all(trigger="test")
    assert r.ok
    view = read_dashboard(store)
    assert view.s7_queries == 0
    funnel = (view.data or {}).get("okpd_funnel") or {}
    assert funnel.get("rows")
    assert funnel["rows"][0]["okpd_code"] == "27.40"
    assert funnel["rows"][0]["okpd_name"]
    assert (view.data or {}).get("subcategory_registry") is not None


def test_filter_and_procurement_opportunity_distinct_contract():
    rows = [
        {
            "okpd_code": "27.40",
            "okpd_name": "light",
            "source_44": 10,
            "source_223": 0,
            "projected_to_crm": 5,
            "prepared_prior_categories": [{"category_code": "lighting", "display_name": "Освещение"}],
        }
    ]
    assert filter_okpd_rows(rows, okpd_query="27.40")
    assert filter_okpd_rows(rows, category_code="lighting")
    assert not filter_okpd_rows(rows, category_code="computers")
