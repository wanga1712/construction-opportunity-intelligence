"""Queue executability contract tests (no DB).

AI_QUEUE_ADMISSION_GATE=NO (CRM-V3-CLEAN-SLATE-ACTUAL-PIPELINE-BUILD-1):
SKIP, NO_COMMERCIAL_ENTRY, WOOD model decisions do NOT gate queue insertion.
Only hard lifecycle states (HOLD/CLOSED via admission) and zero-links block executable status.
"""
from __future__ import annotations

from unittest.mock import patch

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


def test_upsert_skip_not_executable_removed_by_ai_gate_no(monkeypatch):
    """AI_QUEUE_ADMISSION_GATE=NO: SKIP/NCE model output does NOT block queue insertion.

    When research_action=SKIP, the result is now determined by lifecycle admission
    and link count, not by model SKIP output.
    The old SKIP_NOT_EXECUTABLE and NO_COMMERCIAL_ENTRY_NOT_EXECUTABLE guards are removed.
    """
    p = CommercialRoutingV3QueueProducer(enabled=True)

    _adm_class = _make_adm_class(queue_eligible=True, queue_state="ELIGIBLE", research_lane="open_active")

    with patch(
        "src.services.commercial_routing_v3.queue_producer.dry_run_research_admission",
        return_value=_adm_class(),
    ):
        monkeypatch.setattr(p, "_count_links", lambda proc: 0)
        monkeypatch.setattr(
            p, "_load_procurement",
            lambda pid: {
                "id": pid, "source_table": "reestr_contract_44_fz",
                "source_id": 1, "contract_number": "1",
                "end_date": "2099-01-01", "crm_stage": "torgi",
                "award_status": "submission_open",
            },
        )
        monkeypatch.setattr(p, "_load_current_opportunities", lambda pid: [])

        # SKIP research_action with zero links → status is NOT SKIP_NOT_EXECUTABLE (gate removed)
        # Instead: zero-links gate applies → NO_LINKS
        skip_result = p.upsert(
            1,
            {"research_action": "SKIP", "trigger_opportunities": [], "opportunity_track": "DIRECT_SUPPLY"},
            dry_run=False,
        )
        assert skip_result["dispatchable"] is False
        # AI gate removed: must NOT return the old SKIP_NOT_EXECUTABLE
        assert skip_result.get("status") != "SKIP_NOT_EXECUTABLE", (
            "AI_QUEUE_ADMISSION_GATE=NO: SKIP must not produce SKIP_NOT_EXECUTABLE"
        )
        # With zero links, the no-links data reality gate applies
        assert skip_result.get("status") == "NO_LINKS", (
            f"Expected NO_LINKS (zero links), got {skip_result.get('status')}"
        )


def test_upsert_nce_not_blocked_by_ai_gate(monkeypatch):
    """AI_QUEUE_ADMISSION_GATE=NO: NO_COMMERCIAL_ENTRY does NOT block queue insertion.

    The old NO_COMMERCIAL_ENTRY_NOT_EXECUTABLE guard is removed from upsert().
    """
    p = CommercialRoutingV3QueueProducer(enabled=True)

    _adm_class = _make_adm_class(queue_eligible=True, queue_state="ELIGIBLE", research_lane="open_active")

    with patch(
        "src.services.commercial_routing_v3.queue_producer.dry_run_research_admission",
        return_value=_adm_class(),
    ):
        monkeypatch.setattr(p, "_count_links", lambda proc: 0)
        monkeypatch.setattr(
            p, "_load_procurement",
            lambda pid: {
                "id": pid, "source_table": "reestr_contract_44_fz",
                "source_id": 1, "contract_number": "1",
                "end_date": "2099-01-01", "crm_stage": "torgi",
                "award_status": "submission_open",
            },
        )
        monkeypatch.setattr(p, "_load_current_opportunities", lambda pid: [])

        nce_result = p.upsert(
            1,
            {
                "research_action": "LIGHT_RESEARCH",
                "trigger_opportunities": [{"research_action": "LIGHT_RESEARCH"}],
                "opportunity_track": "NO_COMMERCIAL_ENTRY",
            },
            dry_run=False,
        )
        # AI gate removed: must NOT return the old NO_COMMERCIAL_ENTRY_NOT_EXECUTABLE
        assert nce_result.get("status") != "NO_COMMERCIAL_ENTRY_NOT_EXECUTABLE", (
            "AI_QUEUE_ADMISSION_GATE=NO: NCE must not produce NO_COMMERCIAL_ENTRY_NOT_EXECUTABLE"
        )
        assert nce_result["dispatchable"] is False  # still not dispatchable due to zero links


def test_upsert_zero_link_still_not_executable(monkeypatch):
    """Zero links is a DATA REALITY gate, not an AI gate — still blocks queue insertion.

    ZERO_LINK_NOT_EXECUTABLE is preserved regardless of AI_QUEUE_ADMISSION_GATE=NO.
    """
    p = CommercialRoutingV3QueueProducer(enabled=True)

    _adm_class = _make_adm_class(queue_eligible=True, queue_state="ELIGIBLE", research_lane="open_active")

    with patch(
        "src.services.commercial_routing_v3.queue_producer.dry_run_research_admission",
        return_value=_adm_class(),
    ):
        monkeypatch.setattr(p, "_count_links", lambda proc: 0)
        monkeypatch.setattr(
            p, "_load_procurement",
            lambda pid: {
                "id": pid, "source_table": "reestr_contract_44_fz",
                "source_id": 1, "contract_number": "1",
                "end_date": "2099-01-01", "crm_stage": "torgi",
                "award_status": "submission_open",
            },
        )
        monkeypatch.setattr(p, "_load_current_opportunities", lambda pid: [])

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


def _make_adm_class(queue_eligible: bool, queue_state: str, research_lane: str):
    """Factory for mock admission objects that patch correctly."""
    class _Adm:
        pass
    _Adm.queue_eligible = queue_eligible
    _Adm.queue_state = queue_state
    _Adm.research_lane = research_lane
    _Adm.research_purpose = None
    _Adm.research_priority = 30
    _Adm.commercial_lifecycle_state = None
    _Adm.source_lifecycle_event = None
    _Adm.reason = "TEST"
    _Adm.is_active_commercial_lead = True
    _Adm.to_dict = lambda self: {}
    return _Adm
