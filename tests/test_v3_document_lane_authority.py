"""Lane authority: discovery_required ≠ human review."""
from __future__ import annotations

from src.services.commercial_routing_v3.document_lane_authority import (
    apply_current_opportunity_authority,
    is_human_review_required,
)
from src.services.commercial_routing_v3.queue_producer import CommercialRoutingV3QueueProducer
from src.services.commercial_routing_v3.research_queue_lifecycle import (
    dry_run_research_admission,
)


OPEN = {"crm_stage": "torgi", "award_status": "submission_open"}


def test_discovery_required_with_silver_direct_supply_is_open_active() -> None:
    d = dry_run_research_admission(
        procurement=OPEN,
        opportunity_track="DIRECT_SUPPLY",
        routed=True,
        has_valid_category=True,
        discovery_required=True,
        review_required=False,
        research_action="LIGHT_RESEARCH",
        current_effective_medal="SILVER",
        commercial_state="ACTIVE",
    )
    assert d.queue_eligible is True
    assert d.research_lane == "open_active"
    assert d.is_active_commercial_lead is True
    assert d.reason == "OPEN_DIRECT_SUPPLY_CONDITIONAL_YES"


def test_stale_review_flag_does_not_override_gold_embedded_open() -> None:
    d = dry_run_research_admission(
        procurement=OPEN,
        opportunity_track="EMBEDDED_MATERIAL",
        routed=True,
        has_valid_category=True,
        discovery_required=True,
        review_required=True,
        research_action="LIGHT_RESEARCH",
        current_effective_medal="GOLD",
        commercial_state="ACTIVE",
    )
    assert d.research_lane == "open_active"
    assert d.queue_eligible is True


def test_true_human_review_without_category_is_discovery_review() -> None:
    d = dry_run_research_admission(
        procurement=OPEN,
        opportunity_track=None,
        routed=True,
        discovery_required=True,
        review_required=True,
        has_valid_category=False,
    )
    assert d.research_lane == "discovery_review"
    assert d.is_active_commercial_lead is False


def test_wood_not_auto_executable() -> None:
    d = dry_run_research_admission(
        procurement=OPEN,
        opportunity_track="EMBEDDED_MATERIAL",
        routed=True,
        has_valid_category=True,
        research_action="LIGHT_RESEARCH",
        current_effective_medal="WOOD",
        commercial_state="ACTIVE",
    )
    assert d.queue_eligible is False
    assert d.reason == "WOOD_NOT_AUTO_EXECUTABLE"


def test_waiting_still_hold() -> None:
    d = dry_run_research_admission(
        procurement={"crm_stage": "commission", "award_status": "commission"},
        opportunity_track="EMBEDDED_MATERIAL",
        routed=True,
        has_valid_category=True,
        discovery_required=True,
        research_action="LIGHT_RESEARCH",
        current_effective_medal="SILVER",
        commercial_state="WAITING_SOURCE_OUTCOME",
    )
    assert d.queue_eligible is False
    assert d.queue_state == "HOLD"


def test_nce_still_closed() -> None:
    d = dry_run_research_admission(
        procurement=OPEN,
        opportunity_track="NO_COMMERCIAL_ENTRY",
        routed=True,
        has_valid_category=True,
        discovery_required=True,
    )
    assert d.queue_eligible is False
    assert d.reason == "NO_COMMERCIAL_ENTRY"


def test_awarded_embedded_follow_up_despite_discovery_flag() -> None:
    d = dry_run_research_admission(
        procurement={"crm_stage": "razygranye", "award_status": "awarded"},
        opportunity_track="EMBEDDED_MATERIAL",
        routed=True,
        has_valid_category=True,
        discovery_required=True,
        research_action="LIGHT_RESEARCH",
        current_effective_medal="SILVER",
        commercial_state="FOLLOW_UP_AWARDED",
    )
    assert d.queue_eligible is True
    assert d.research_lane == "awarded_follow_up"


def test_overlay_clears_stale_discovery_for_current_silver() -> None:
    decision = {
        "discovery_required": True,
        "review_required": True,
        "research_action": "DISCOVER_COMMERCIAL_CATEGORY",
        "queue_lane": "discovery_review",
        "trigger_opportunities": [],
    }
    out = apply_current_opportunity_authority(
        decision,
        [
            {
                "commercial_category_code": "computers",
                "opportunity_track": "DIRECT_SUPPLY",
                "research_action": "LIGHT_RESEARCH",
                "current_effective_medal": "SILVER",
                "commercial_state": "ACTIVE",
            }
        ],
    )
    assert out["discovery_required"] is False
    assert out["review_required"] is False
    assert out["document_research_required"] is True
    assert out["human_review_required"] is False
    assert out["candidate_medal"] == "SILVER"
    assert out["opportunity_track"] == "DIRECT_SUPPLY"


def test_human_review_helper_false_when_actionable_hypothesis() -> None:
    assert (
        is_human_review_required(
            discovery_required=True,
            review_required=True,
            has_valid_category=True,
            track="DIRECT_SUPPLY",
            research_action="LIGHT_RESEARCH",
            current_effective_medal="SILVER",
            commercial_state="ACTIVE",
        )
        is False
    )


def test_producer_upsert_17285_like_open_active(monkeypatch) -> None:
    p = CommercialRoutingV3QueueProducer(enabled=True)
    monkeypatch.setattr(p, "_count_links", lambda proc: 2)
    monkeypatch.setattr(
        p,
        "_load_procurement",
        lambda pid: {
            "id": pid,
            "source_table": "reestr_contract_223_fz",
            "source_id": 145670,
            "contract_number": "32615626098",
            "end_date": "2027-01-21",
            "crm_stage": "torgi",
            "award_status": "submission_open",
        },
    )
    monkeypatch.setattr(
        p,
        "_load_current_opportunities",
        lambda pid: [
            {
                "commercial_category_code": "computers",
                "opportunity_track": "DIRECT_SUPPLY",
                "research_action": "LIGHT_RESEARCH",
                "current_effective_medal": "SILVER",
                "commercial_state": "ACTIVE",
            }
        ],
    )
    captured = {}

    def _fake_upsert(task, *, status="PENDING"):
        captured["task"] = task
        captured["status"] = status
        return {"action": "updated", "queue_id": 44, "status": status, **task}

    monkeypatch.setattr(p, "_upsert_queue_task", _fake_upsert)
    out = p.upsert(
        17285,
        {
            "research_action": "DISCOVER_COMMERCIAL_CATEGORY",
            "discovery_required": True,
            "review_required": True,
            "opportunity_track": None,
            "trigger_opportunities": [],
            "candidate_medal": "SILVER",
        },
        dry_run=False,
    )
    assert out["dispatchable"] is True
    assert captured["task"]["queue_lane"] == "open_active"
    assert captured["status"] == "PENDING"
