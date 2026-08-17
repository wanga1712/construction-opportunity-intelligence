from __future__ import annotations

from src.services.s13_v2_queue_producer import S13V2QueueProducer


def test_discovery_required_allows_queue_when_no_category_opps() -> None:
    producer = S13V2QueueProducer()
    a = {
        "procurement_id": 123,
        "source_table": "reestr_contract_44_fz",
        "source_id": 1,
        "contract_number": "CN-1",
        "assessment_id": 55,
        "candidate_level": None,
        "candidate_score": None,
        "normalized_result": {
            "category_opportunities": [],
            "discovery_required": True,
            "overall_research_action": "LIGHT_RESEARCH",
        },
    }

    out = producer._process_assessment(a, dry_run=True)
    assert out is not None
    assert out["research_action"] == "LIGHT_RESEARCH"
    assert out["queue_lane"] == "open_active"
    assert out["category_codes"] == []

