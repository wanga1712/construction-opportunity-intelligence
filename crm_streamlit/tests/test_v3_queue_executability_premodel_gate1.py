"""Queue executability contract tests (no DB)."""
from __future__ import annotations

from src.services.commercial_routing_v3.queue_producer import CommercialRoutingV3QueueProducer, _SKIP
from src.domain.commercial_routing_v3 import ResearchAction


def test_skip_in_skip_set():
    assert ResearchAction.SKIP.value in _SKIP


def test_decide_skip_returns_none_without_trigger():
    p = CommercialRoutingV3QueueProducer(enabled=False)
    assert (
        p.decide_from_normalized(
            {
                "overall_research_action": "SKIP",
                "commercial_category_hypotheses": [
                    {"research_action": "SKIP", "category_code": "x"}
                ],
            }
        )
        is None
    )


def test_upsert_blocks_skip_and_nce_and_zero_link(monkeypatch):
    p = CommercialRoutingV3QueueProducer(enabled=True)
    monkeypatch.setattr(p, "_count_links", lambda proc: 0)
    monkeypatch.setattr(
        p,
        "_load_procurement",
        lambda pid: {
            "id": pid,
            "source_table": "reestr_contract_44_fz",
            "source_id": 1,
            "contract_number": "1",
            "end_date": "2099-01-01",
            "crm_stage": "torgi",
            "award_status": "submission_open",
        },
    )
    monkeypatch.setattr(p, "_load_current_opportunities", lambda pid: [])
    from src.services.commercial_routing_v3 import research_queue_lifecycle as rql

    class Adm:
        queue_eligible = True
        queue_state = "ELIGIBLE"
        research_lane = "open_active"
        research_priority = 30

        def to_dict(self):
            return {}

    monkeypatch.setattr(rql, "dry_run_research_admission", lambda **kw: Adm())

    skip = p.upsert(
        1,
        {"research_action": "SKIP", "trigger_opportunities": [], "opportunity_track": "DIRECT_SUPPLY"},
        dry_run=False,
    )
    assert skip["status"] == "SKIP_NOT_EXECUTABLE"
    assert skip["dispatchable"] is False

    nce = p.upsert(
        1,
        {
            "research_action": "LIGHT_RESEARCH",
            "trigger_opportunities": [{"research_action": "LIGHT_RESEARCH"}],
            "opportunity_track": "NO_COMMERCIAL_ENTRY",
        },
        dry_run=False,
    )
    assert nce["status"] == "NO_COMMERCIAL_ENTRY_NOT_EXECUTABLE"

    zero = p.upsert(
        1,
        {
            "research_action": "LIGHT_RESEARCH",
            "trigger_opportunities": [{"research_action": "LIGHT_RESEARCH", "category_code": "c"}],
            "opportunity_track": "DIRECT_SUPPLY",
            "candidate_medal": "BRONZE",
            "primary_category": "c",
            "opportunity_associations": [{"category_code": "c"}],
        },
        dry_run=False,
    )
    assert zero["status"] == "NO_LINKS"
    assert zero["dispatchable"] is False
