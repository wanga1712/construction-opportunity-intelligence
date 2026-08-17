"""Unit tests for V3 research queue lifecycle dry-run contract."""
from __future__ import annotations

from src.services.commercial_routing_v3.research_queue_lifecycle import (
    ResearchPurpose,
    classify_doc_value,
    dry_run_research_admission,
    select_docs_for_research,
)


def test_projected_unrouted_not_eligible() -> None:
    d = dry_run_research_admission(
        procurement={"crm_stage": "torgi", "award_status": "submission_open"},
        routed=False,
    )
    assert d.queue_eligible is False
    assert d.queue_state == "NOT_ROUTED"
    assert d.reason == "PROJECTED_PENDING_ROUTING"


def test_open_embedded_eligible() -> None:
    d = dry_run_research_admission(
        procurement={"crm_stage": "torgi", "award_status": "submission_open"},
        opportunity_track="EMBEDDED_MATERIAL",
        routed=True,
        has_valid_category=True,
    )
    assert d.queue_eligible is True
    assert d.research_purpose == ResearchPurpose.FIND_EMBEDDED_MATERIAL.value


def test_awarded_direct_supply_closed() -> None:
    d = dry_run_research_admission(
        procurement={"crm_stage": "razygranye", "award_status": "awarded"},
        opportunity_track="DIRECT_SUPPLY",
        routed=True,
        has_valid_category=True,
    )
    assert d.queue_eligible is False
    assert d.queue_state == "CLOSED_NO_RESEARCH"


def test_awarded_design_follow_up() -> None:
    d = dry_run_research_admission(
        procurement={"crm_stage": "razygranye", "award_status": "awarded"},
        opportunity_track="DESIGN_REQUIREMENT",
        routed=True,
        has_valid_category=True,
    )
    assert d.queue_eligible is True
    assert d.research_lane == "awarded_follow_up"
    assert d.research_purpose == ResearchPurpose.POST_AWARD_FOLLOW_UP.value


def test_waiting_hold() -> None:
    d = dry_run_research_admission(
        procurement={"crm_stage": "commission", "award_status": "commission"},
        opportunity_track="EMBEDDED_MATERIAL",
        routed=True,
        has_valid_category=True,
    )
    assert d.queue_eligible is False
    assert d.queue_state == "HOLD"


def test_discovery_review_no_fake_category() -> None:
    d = dry_run_research_admission(
        procurement={"crm_stage": "torgi", "award_status": "submission_open"},
        opportunity_track=None,
        routed=True,
        discovery_required=True,
        review_required=True,
        has_valid_category=False,
    )
    assert d.queue_eligible is True
    assert d.research_lane == "discovery_review"
    assert d.fake_category_allowed is False
    assert d.fake_medal_allowed is False
    assert d.is_active_commercial_lead is False


def test_doc_selection_prefers_high_value_names() -> None:
    links = [
        {"file_name": "Протокол заседания.pdf", "url": "u1"},
        {"file_name": "Техническое задание.docx", "url": "u2"},
        {"file_name": "Смета.xls", "url": "u3"},
        {"file_name": "photo.jpg", "url": "u4"},
    ]
    assert classify_doc_value("Техническое задание.docx") == "HIGH"
    plan = select_docs_for_research(links)
    names = [x["file_name"] for x in plan["selected"]]
    assert "Техническое задание.docx" in names
    assert "Смета.xls" in names
    assert plan["low_count"] >= 1
