"""Tests for V3 projection identity, admission, and commercial visibility."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.services.commercial_routing_v3 import projection as proj


def test_normalize_contract_number():
    assert proj.normalize_contract_number(" 0173200001424001779 ") == "0173200001424001779"
    assert proj.normalize_contract_number("") is None
    assert proj.normalize_contract_number("   ") is None
    assert proj.normalize_contract_number(None) is None
    # leading zeroes preserved (no numeric cast)
    assert proj.normalize_contract_number("000123") == "000123"
    assert proj.normalize_contract_number("000123") != proj.normalize_contract_number("123")


def test_v3_projection_default_disabled(monkeypatch):
    monkeypatch.delenv(proj.ENV_V3_PROJECTION_ENABLED, raising=False)
    assert proj.v3_projection_enabled() is False
    assert proj.V3_PROJECTION_DEFAULT_ENABLED is False
    d = proj.admit_source_row(
        source_table="reestr_contract_44_fz",
        source_id=1,
        contract_number="X",
        auction_name="Title",
    )
    assert d.admit is False
    assert d.reason == proj.NotProjectedReason.FEATURE_DISABLED


def _open(contour_table: str, cn: str, sid: int, title: str = "Поставка"):
    return {
        "source_table": contour_table,
        "source_id": sid,
        "contract_number": cn,
        "auction_name": title,
    }


def test_44_open_projects_once():
    store = proj.InMemoryProjectionStore()
    row1, d1 = proj.project_source_row(
        store, _open("reestr_contract_44_fz", "CN-44-1", 100), enabled=True
    )
    row2, d2 = proj.project_source_row(
        store, _open("reestr_contract_44_fz", "CN-44-1", 100), enabled=True
    )
    assert d1.admit and d2.admit
    assert row1["id"] == row2["id"]
    assert len(store.rows) == 1


def test_223_open_projects_once():
    store = proj.InMemoryProjectionStore()
    a, _ = proj.project_source_row(
        store, _open("reestr_contract_223_fz", "CN-223-1", 10), enabled=True
    )
    b, _ = proj.project_source_row(
        store, _open("reestr_contract_223_fz", "CN-223-1", 10), enabled=True
    )
    assert a["id"] == b["id"]
    assert len(store.rows) == 1


def test_44_open_commission_awarded_same_id():
    store = proj.InMemoryProjectionStore()
    cn = "CN-44-LIFE"
    r1, _ = proj.project_source_row(
        store, _open("reestr_contract_44_fz", cn, 100), enabled=True
    )
    r2, _ = proj.project_source_row(
        store,
        {
            "source_table": "reestr_contract_44_fz_commission_work",
            "source_id": 200,
            "contract_number": cn,
            "auction_name": "Поставка",
        },
        enabled=True,
    )
    r3, _ = proj.project_source_row(
        store,
        {
            "source_table": "reestr_contract_44_fz_awarded",
            "source_id": 300,
            "contract_number": cn,
            "auction_name": "Поставка",
            "updated_at": datetime.now(timezone.utc),
        },
        enabled=True,
        crm_has_lifecycle_identity=True,
    )
    assert r1["id"] == r2["id"] == r3["id"]
    assert len(store.rows) == 1
    assert r3["source_table"] == "reestr_contract_44_fz_awarded"
    assert r3["source_id"] == 300
    assert len(store.audit) >= 3


def test_223_open_commission_awarded_same_id():
    store = proj.InMemoryProjectionStore()
    cn = "CN-223-LIFE"
    r1, _ = proj.project_source_row(
        store, _open("reestr_contract_223_fz", cn, 11), enabled=True
    )
    r2, _ = proj.project_source_row(
        store,
        {
            "source_table": "reestr_contract_223_fz_commission_work",
            "source_id": 22,
            "contract_number": cn,
        },
        enabled=True,
    )
    r3, _ = proj.project_source_row(
        store,
        {
            "source_table": "reestr_contract_223_fz_awarded",
            "source_id": 33,
            "contract_number": cn,
        },
        enabled=True,
        crm_has_lifecycle_identity=True,
    )
    assert r1["id"] == r2["id"] == r3["id"]
    assert len(store.rows) == 1


def test_cross_contour_same_number_distinct():
    store = proj.InMemoryProjectionStore()
    a, _ = proj.project_source_row(
        store, _open("reestr_contract_44_fz", "SAME-X", 1), enabled=True
    )
    b, _ = proj.project_source_row(
        store, _open("reestr_contract_223_fz", "SAME-X", 2), enabled=True
    )
    assert a["id"] != b["id"]
    assert len(store.rows) == 2


def test_null_identity_no_false_merge():
    store = proj.InMemoryProjectionStore()
    a, _ = proj.project_source_row(
        store,
        {"source_table": "reestr_contract_44_fz", "source_id": 1, "contract_number": None, "auction_name": "A"},
        enabled=True,
    )
    b, _ = proj.project_source_row(
        store,
        {"source_table": "reestr_contract_44_fz", "source_id": 2, "contract_number": "  ", "auction_name": "B"},
        enabled=True,
    )
    assert a["id"] != b["id"]


def test_fallback_identity_upgrade_safe():
    existing = {"id": 7, "contract_number": None, "source_table": "reestr_contract_44_fz", "source_id": 1}
    assert (
        proj.decide_fallback_identity_upgrade(existing_row=existing, new_contract_number=" CN1 ")
        == proj.IdentityUpgradeResult.UPGRADED
    )
    assert (
        proj.decide_fallback_identity_upgrade(
            existing_row=existing, new_contract_number="CN1", stable_owner_id=99
        )
        == proj.IdentityUpgradeResult.REVIEW_REQUIRED
    )


def test_target_projection_no_processed_docs_constant():
    assert proj.TARGET_PROJECTION_USES_S7_PROCESSED_DOCUMENTS is False
    assert proj.LEGACY_COMMERCIAL_FILTER_BEFORE_V3 is False
    assert proj.OPEN_REQUIRES_DOCS_PROCESSED is False
    assert proj.OPEN_REQUIRES_USER_OKPD is False
    assert proj.OPEN_REQUIRES_KEYWORD_MATCH is False


def test_full_awarded_history_not_imported():
    store = proj.InMemoryProjectionStore()
    old = datetime.now(timezone.utc) - timedelta(days=30)
    wm = datetime.now(timezone.utc) - timedelta(days=1)
    row, decision = proj.project_source_row(
        store,
        {
            "source_table": "reestr_contract_44_fz_awarded",
            "source_id": 999,
            "contract_number": "HIST-OLD",
            "updated_at": old,
            "auction_name": "old",
        },
        awarded_watermark=wm,
        enabled=True,
    )
    assert row is None
    assert decision.reason == proj.NotProjectedReason.FULL_AWARDED_HISTORY_EXCLUDED
    assert proj.FULL_AWARDED_HISTORY_IMPORTED is False


def test_awarded_existing_identity_updates_same_row():
    store = proj.InMemoryProjectionStore()
    cn = "AW-EXIST"
    r1, _ = proj.project_source_row(
        store, _open("reestr_contract_44_fz", cn, 5), enabled=True
    )
    r2, d2 = proj.project_source_row(
        store,
        {
            "source_table": "reestr_contract_44_fz_awarded",
            "source_id": 50,
            "contract_number": cn,
            "updated_at": datetime.now(timezone.utc) - timedelta(days=100),
        },
        enabled=True,
    )
    assert d2.admit
    assert r2["id"] == r1["id"]


def test_raw_projected_not_active_lead_and_feed_gate():
    assert proj.RAW_PROJECTED_PROCUREMENT_IS_ACTIVE_LEAD is False
    # 13648 projected, 0 opportunities → feed empty
    assert (
        proj.active_feed_includes_procurement([], v3_schema_ready=True) is False
    )
    # Even with many projected rows conceptually — feed uses opportunities only
    fake_projected_count = 13648
    feed = [
        p
        for p in range(fake_projected_count)
        if proj.active_feed_includes_procurement([], v3_schema_ready=True)
    ]
    assert feed == []


def test_active_feed_requires_visible_opportunity():
    opps = [{"commercial_state": "CLOSED"}, {"commercial_state": "SUPPRESSED"}]
    assert proj.active_feed_includes_procurement(opps, v3_schema_ready=True) is False
    opps2 = [{"commercial_state": "CLOSED"}, {"commercial_state": "FOLLOW_UP_AWARDED"}]
    assert proj.active_feed_includes_procurement(opps2, v3_schema_ready=True) is True
    # V3 not ready → opportunity-gated feed does not activate
    assert proj.active_feed_includes_procurement(opps2, v3_schema_ready=False) is False


def test_container_visibility_aggregates_opportunities():
    opps = [
        {"commercial_state": "CLOSED", "category": "lighting"},
        {"commercial_state": "FOLLOW_UP_AWARDED", "category": "drainage"},
    ]
    assert proj.container_visible_from_opportunities(opps) is True
    assert (
        proj.container_visible_from_opportunities(
            [{"commercial_state": "CLOSED"}, {"commercial_state": "ARCHIVED"}]
        )
        is False
    )


def test_no_category_discovery_preserved():
    state = proj.routing_state_from_ai_status(
        "COMPLETED",
        has_visible_opportunity=False,
        discovery_required=True,
        skip_no_opportunity=False,
    )
    assert state == proj.ProcurementRoutingState.PENDING_ROUTING


def test_skip_no_opportunity_retention_state():
    state = proj.routing_state_from_ai_status(
        "COMPLETED",
        has_visible_opportunity=False,
        discovery_required=False,
        skip_no_opportunity=True,
    )
    assert state == proj.ProcurementRoutingState.NO_CURRENT_OPPORTUNITY


def test_parallel_legacy_writer_forbidden_constant():
    assert proj.V3_PROJECTION_PARALLEL_LEGACY_WRITER is False


def test_source_table_is_not_identity():
    store = proj.InMemoryProjectionStore()
    cn = "PROV-ONLY"
    r1, _ = proj.project_source_row(
        store, _open("reestr_contract_44_fz", cn, 1), enabled=True
    )
    r2, _ = proj.project_source_row(
        store,
        {
            "source_table": "reestr_contract_44_fz_commission_work",
            "source_id": 99,
            "contract_number": f" {cn} ",
            "auction_name": "x",
        },
        enabled=True,
    )
    assert r1["id"] == r2["id"]
    assert len(store.rows) == 1


def test_open_admission_no_docs_requirement():
    d = proj.admit_source_row(
        source_table="reestr_contract_44_fz",
        source_id=1,
        contract_number="Z",
        auction_name="Title only",
        enabled=True,
    )
    assert d.admit is True
    assert d.stage == proj.SourceStage.OPEN
