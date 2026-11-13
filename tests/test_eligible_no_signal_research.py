from src.services.commercial_routing_v3.reconciliation_document_plan import (
    _planning_opportunities,
)
from src.services.commercial_routing_v3.document_queue_reconciliation import (
    _current_eligible_workset,
)
from src.services.commercial_routing_v3.queue_plan_v2 import build_queue_plan_v2
from src.services.commercial_routing_v3.routing_initial_pass import (
    SELECT_NO_PRIORITY_SIGNAL,
    SELECT_OKPD,
    SKIP_NOT_ELIGIBLE,
    initial_pass_decision,
)
from src.services.commercial_routing_v3.routing_priority import sort_lane_buckets


def _authority(**overrides):
    row = {
        "admission_state": "ELIGIBLE",
        "admission_policy_version": "BUSINESS_RESEARCH_ADMISSION_V2",
        "source_lifecycle": "OPEN",
        "procurement_scope_type": "WORKS_WITH_EMBEDDED_PRODUCTS",
    }
    row.update(overrides)
    return row


def test_no_initial_signal_is_selectable_low_priority(monkeypatch):
    monkeypatch.setenv("CRM_V3_INITIAL_PASS_MODE", "1")

    selected, reason = initial_pass_decision(_authority(), False, False, False)

    assert selected is True
    assert reason == SELECT_NO_PRIORITY_SIGNAL


def test_initial_signal_selects_high_priority(monkeypatch):
    monkeypatch.setenv("CRM_V3_INITIAL_PASS_MODE", "1")

    selected, reason = initial_pass_decision(_authority(), True, False, False)

    assert selected is True
    assert reason == SELECT_OKPD


def test_not_eligible_remains_blocked(monkeypatch):
    monkeypatch.setenv("CRM_V3_INITIAL_PASS_MODE", "1")

    selected, reason = initial_pass_decision(
        _authority(admission_state="EXCLUDED"),
        True,
        True,
        True,
    )

    assert selected is False
    assert reason == SKIP_NOT_ELIGIBLE


def test_high_signal_sorts_before_low_signal_in_same_lane():
    rows = [
        {
            "id": 1,
            "okpd_code": "99.99",
            "routing_lane": "ACTIVE_OPEN",
            "initial_pass_reason": "INITIAL_NO_PRIORITY_SIGNAL",
        },
        {
            "id": 2,
            "okpd_code": "99.99",
            "routing_lane": "ACTIVE_OPEN",
            "research_priority": "HIGH",
        },
    ]

    ordered = sort_lane_buckets(rows, [])

    assert [row["id"] for row in ordered] == [2, 1]


def test_no_opportunity_gets_planning_only_object_discovery_context():
    source = {
        "id": 485013,
        "procurement_id": 485013,
        "crm_stage": "torgi",
        "source_table": "reestr_contract_44_fz",
    }

    opportunities = _planning_opportunities(485013, source, [])

    assert len(opportunities) == 1
    assert opportunities[0]["planning_context_only"] is True
    assert opportunities[0]["opportunity_track"] == "EMBEDDED_MATERIAL"
    assert opportunities[0]["commercial_category_code"] is None


def test_reconciliation_can_bound_queue_write_to_canary_ids():
    class _Crm:
        def __init__(self):
            self.sql = None
            self.params = None

        def execute_query(self, sql, params=None):
            self.sql = sql
            self.params = params
            return []

    crm = _Crm()

    _current_eligible_workset(crm, procurement_ids=[485050, 485013, 485050])

    assert "a.procurement_id = ANY(%s)" in crm.sql
    assert crm.params == ([485013, 485050],)


def test_left_join_placeholder_is_not_a_real_opportunity():
    class _Crm:
        def execute_query(self, sql, params=None):
            return [
                {
                    "procurement_id": 485013,
                    "opportunity_id": None,
                    "commercial_category_code": None,
                    "category_code": None,
                    "opportunity_track": None,
                    "id": 485013,
                    "source_table": "reestr_contract_44_fz",
                }
            ]

    _, sources, opportunities = _current_eligible_workset(_Crm())

    assert set(sources) == {485013}
    assert opportunities == {}


def test_no_opportunity_builds_document_research_plan_without_fake_category():
    source = {
        "id": 485013,
        "procurement_id": 485013,
        "crm_stage": "torgi",
        "award_status": "submission_open",
        "source_status": "open",
        "source_table": "reestr_contract_44_fz",
        "start_date": "2026-11-13",
        "end_date": "2026-12-31",
    }
    opportunities = _planning_opportunities(485013, source, [])
    documents = [
        {
            "id": 77,
            "procurement_id": 485013,
            "file_name": "Смета.xlsx",
            "source_table": "reestr_contract_44_fz",
            "physical_download_key": "doc-77",
            "download_status": "PENDING",
        }
    ]

    plan = build_queue_plan_v2(
        procurement=opportunities[0],
        opportunities=opportunities,
        documents=documents,
        pipeline_generation="S13_V4_EXHAUSTIVE_CONTEXT",
    )

    assert plan["research_action_v2"] == "DOCUMENT_RESEARCH_REQUIRED"
    assert plan["document_routing_mode"] == "OBJECT_PROJECT"
    assert plan["category_codes"] == []
    assert 77 in plan["selected_source_document_ids"]
