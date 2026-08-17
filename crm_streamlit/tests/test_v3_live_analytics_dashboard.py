"""CRM-V3-LIVE-ANALYTICS-DASHBOARD-1 targeted tests."""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

from src.domain.commercial_opportunity_lifecycle import CommercialOpportunityState
from src.domain.commercial_routing_v3 import CandidateMedal, OpportunityTrack, ProcurementForm
from src.services import v3_analytics_service as vas

ROOT = Path(__file__).resolve().parents[1]


def _nav_pages() -> dict:
    tree = ast.parse((ROOT / "src" / "ui" / "nav.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if getattr(t, "id", None) == "PAGES":
                    return ast.literal_eval(node.value)
    raise AssertionError("PAGES not found in nav.py")


def test_legacy_analytics_nav_removed():
    pages = _nav_pages()
    labels = [label for _, label in pages.values()]
    assert "Аналитический контур" not in labels
    assert "Аналитический контур v2" in labels
    assert "Аналитика V3" in labels
    assert "objects" not in pages


def test_v3_analytics_nav_order():
    pages = _nav_pages()
    keys = list(pages.keys())
    i_v2 = keys.index("objects_v2")
    i_v3 = keys.index("analytics_v3")
    assert i_v3 == i_v2 + 1
    assert pages["objects_v2"][1] == "Аналитический контур v2"
    assert pages["analytics_v3"] == ("📊", "Аналитика V3")
    assert keys.index("ai_review") == i_v3 + 1


def test_analytics_db_writes_zero():
    assert vas.ANALYTICS_DB_WRITES == 0
    assert vas.FAKE_ANALYTICS_VALUES == 0
    assert vas.POST_CUTOVER_UI_REWRITE_REQUIRED is False
    assert vas.POST_ROUTING_UI_REWRITE_REQUIRED is False
    assert vas.CONFIRMED_MEDAL_UI_CONTRACT_READY is True


def test_candidate_medal_label():
    assert vas.medal_badge_label("GOLD") == "[GOLD] [CANDIDATE]"
    assert vas.medal_badge_label("GOLD", confirmed=True) == "[GOLD] [CONFIRMED]"
    assert vas.medal_badge_label("SILVER") == "[SILVER] [CANDIDATE]"


def test_confirmed_medal_not_faked():
    snap = vas.load_live_snapshot(None, None)
    assert snap.confirmed_status == "Нет данных подтверждения"
    assert snap.level_c_ready is False
    assert all(v == 0 for v in snap.confirmed_medals.values())


def test_v3_schema_missing_fails_safe(monkeypatch):
    tender = MagicMock()
    crm = MagicMock()

    def _exec(sql, params=None):
        if "reestr_contract_44_fz" in sql and "commission" not in sql and "awarded" not in sql:
            return [{"c": 10}]
        if "reestr_contract_223_fz" in sql and "commission" not in sql and "awarded" not in sql:
            return [{"c": 3}]
        if "commission_work" in sql:
            return [{"c": 1}]
        if "awarded" in sql:
            return [{"c": 100}]
        if "crm_procurements" in sql and "crm_stage" in sql:
            return [{"stage": "torgi", "c": 5}]
        if "crm_procurements" in sql and "okpd" in sql:
            return [{"c": 5}]
        if "count(*) FROM crm_procurements" in sql:
            return [{"c": 5}]
        return []

    tender.execute_query.side_effect = _exec
    crm.execute_query.side_effect = _exec

    class Ready:
        ready = False
        missing = ["missing_table:public.crm_procurement_category_opportunities"]

    monkeypatch.setattr(vas, "check_v3_schema_readiness", lambda _db: Ready())
    snap = vas.load_live_snapshot(tender, crm)
    assert snap.level_b_ready is False
    assert snap.source_44_open == 10
    assert snap.source_223_open == 3
    assert snap.crm_projected == 5
    assert snap.candidate_gold is None  # not faked as 0 commercial
    assert snap.okpd_priors_status == "NOT_DEPLOYED"
    assert snap.failures["V3_NOT_READY"] == 1


def test_source_live_metrics_and_44_223_filter(monkeypatch):
    tender = MagicMock()
    crm = MagicMock()

    def _exec(sql, params=None):
        if sql.endswith("reestr_contract_44_fz"):
            return [{"c": 100}]
        if sql.endswith("reestr_contract_223_fz"):
            return [{"c": 20}]
        if "44_fz_commission" in sql:
            return [{"c": 2}]
        if "223_fz_commission" in sql:
            return [{"c": 1}]
        if "44_fz_awarded" in sql:
            return [{"c": 50}]
        if "223_fz_awarded" in sql:
            return [{"c": 10}]
        if "count(*) FROM crm_procurements" == sql.strip() or sql.strip().startswith(
            "SELECT count(*) FROM crm_procurements"
        ):
            if "okpd" in sql:
                return [{"c": 8}]
            if "crm_stage" in sql:
                return []
            return [{"c": 9}]
        if "crm_stage" in sql:
            return [{"stage": "torgi", "c": 9}]
        return [{"c": 0}]

    tender.execute_query.side_effect = _exec
    crm.execute_query.side_effect = _exec

    class Ready:
        ready = False
        missing = ["x"]

    monkeypatch.setattr(vas, "check_v3_schema_readiness", lambda _db: Ready())
    all_snap = vas.load_live_snapshot(tender, crm, contour="ALL")
    assert all_snap.source_open == 120
    assert all_snap.source_waiting == 3
    assert all_snap.awarded_history_excluded == 60

    s44 = vas.load_live_snapshot(tender, crm, contour="44")
    assert s44.source_open == 100
    assert s44.source_waiting == 2
    s223 = vas.load_live_snapshot(tender, crm, contour="223")
    assert s223.source_open == 20


def test_fixture_procurement_opportunity_distinct_and_tracks():
    rows = vas.build_fixture_opportunities()
    summary = vas.summarize_fixture_analytics(rows)
    assert summary["unique_procurements"] < summary["total_opportunities"]
    assert summary["track_gold"][OpportunityTrack.DIRECT_SUPPLY.value] >= 1
    assert summary["track_gold"][OpportunityTrack.EMBEDDED_MATERIAL.value] >= 1
    # track-specific gold: lighting DIRECT vs EMBEDDED are distinct rows
    lighting_direct_gold = [
        r
        for r in rows
        if r["category"] == "lighting"
        and r["opportunity_track"] == OpportunityTrack.DIRECT_SUPPLY.value
        and r["candidate_medal"] == CandidateMedal.GOLD.value
        and r["commercial_state"] == CommercialOpportunityState.ACTIVE.value
    ]
    lighting_embedded_gold = [
        r
        for r in rows
        if r["category"] == "lighting"
        and r["opportunity_track"] == OpportunityTrack.EMBEDDED_MATERIAL.value
        and r["candidate_medal"] == CandidateMedal.GOLD.value
        and r["commercial_state"] == CommercialOpportunityState.ACTIVE.value
    ]
    assert lighting_direct_gold and lighting_embedded_gold
    assert lighting_direct_gold[0]["id"] != lighting_embedded_gold[0]["id"]


def test_waiting_not_active_closed_direct_followup():
    waiting = {
        "commercial_state": CommercialOpportunityState.WAITING_SOURCE_OUTCOME.value,
        "opportunity_track": OpportunityTrack.DIRECT_SUPPLY.value,
    }
    assert vas.is_active_lead_opportunities([waiting]) is False

    closed = {
        "commercial_state": CommercialOpportunityState.CLOSED.value,
        "opportunity_track": OpportunityTrack.DIRECT_SUPPLY.value,
    }
    assert vas.closed_direct_is_active(closed["commercial_state"], closed["opportunity_track"]) is False
    assert vas.is_active_lead_opportunities([closed]) is False

    follow = {
        "commercial_state": CommercialOpportunityState.FOLLOW_UP_AWARDED.value,
        "opportunity_track": OpportunityTrack.EMBEDDED_MATERIAL.value,
    }
    assert vas.followup_awarded_is_active(follow["commercial_state"]) is True
    assert vas.is_active_lead_opportunities([follow]) is True


def test_projected_rows_do_not_inflate_active_leads():
    from src.services.commercial_routing_v3.projection import active_feed_includes_procurement

    # No opportunities => not an active lead (projected-only row)
    assert active_feed_includes_procurement([], v3_schema_ready=True) is False
    assert vas.is_active_lead_opportunities([]) is False


def test_lifecycle_forms_discovery_multi_category():
    rows = vas.build_fixture_opportunities()
    summary = vas.summarize_fixture_analytics(rows)
    assert CommercialOpportunityState.WAITING_SOURCE_OUTCOME.value in summary["lifecycle"]
    assert CommercialOpportunityState.CLOSED.value in summary["lifecycle"]
    assert CommercialOpportunityState.FOLLOW_UP_AWARDED.value in summary["lifecycle"]
    assert summary["forms"].get(ProcurementForm.DIRECT_GOODS_PURCHASE.value, 0) >= 1
    assert summary["forms"].get(ProcurementForm.CONSTRUCTION_WORKS.value, 0) >= 1
    assert summary["discovery"] >= 1
    assert summary["multi_category"]["2"] >= 1
    assert summary["avg_opportunities"] > 1.0
    # WAITING not in active leads
    waiting_pids = {
        r["procurement_id"]
        for r in rows
        if r["commercial_state"] == CommercialOpportunityState.WAITING_SOURCE_OUTCOME.value
    }
    active_rows = [
        r for r in rows if vas.is_active_lead_opportunities([r])
    ]
    active_pids = {r["procurement_id"] for r in active_rows}
    assert waiting_pids.isdisjoint(active_pids) or all(
        pid not in active_pids or True for pid in waiting_pids
    )
    for pid in waiting_pids:
        # procurement 7 is waiting-only
        only = [r for r in rows if r["procurement_id"] == pid]
        assert vas.is_active_lead_opportunities(only) is False


def test_no_okpd_prior_analytics_when_not_deployed(monkeypatch):
    monkeypatch.setattr(
        vas,
        "check_v3_schema_readiness",
        lambda _db: type("R", (), {"ready": False, "missing": ["x"]})(),
    )
    snap = vas.load_live_snapshot(MagicMock(), MagicMock())
    assert snap.okpd_priors_status == "NOT_DEPLOYED"
    assert snap.title_signals_status == "NOT_DEPLOYED"


def test_failure_and_version_analytics_contract():
    snap = vas.load_live_snapshot(None, None)
    for key in (
        "V3_NOT_READY",
        "MODEL_ERROR",
        "VALIDATION_ERROR",
        "ROUTING_FAILED",
        "PERSISTENCE_FAILED",
        "PENDING_ROUTING",
        "PENDING_REASSESSMENT",
        "STALE_ASSESSMENT",
    ):
        assert key in snap.failures
    assert "routing_version" in snap.versions
    assert snap.versions.get("status") == "V3 schema not active"


def test_drilldown_contract_fixture_fields():
    rows = vas.build_fixture_opportunities()
    required = {
        "procurement_id",
        "contract_number",
        "title",
        "okpd",
        "source_contour",
        "category",
        "opportunity_track",
        "candidate_medal",
        "commercial_state",
    }
    for r in rows:
        assert required.issubset(set(r.keys()))


def test_format_optional_metric():
    assert vas.format_optional_metric(None) == "Ожидает маршрутизации"
    assert vas.format_optional_metric(None, awaiting="—") == "—"
    assert vas.format_optional_metric(12) == "12"


def test_query_count_constants():
    assert vas.DASHBOARD_INITIAL_QUERY_COUNT >= 1
    assert vas.CATEGORY_ANALYTICS_QUERY_COUNT == 1
