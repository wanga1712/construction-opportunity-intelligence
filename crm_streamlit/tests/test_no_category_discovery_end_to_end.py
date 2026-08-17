from __future__ import annotations

from typing import Any, Dict

from src.services.candidate_policy import CandidatePolicy
from src.services.commercial_routing_v3.runtime_adapter import decision_to_normalized_result
from src.services.s13_v2_queue_producer import S13V2QueueProducer


def test_no_category_discovery_end_to_end() -> None:
    # Mimic: V3 discovery_required=True, no category hypotheses.
    decision = {
        "source_contour": None,
        "procurement_form": None,
        "analysis_modes": [],
        "discovery_required": True,
        "overall_research_action": "LIGHT_RESEARCH",
        "commercial_category_hypotheses": [],
    }
    procurement = {"contract_number": "DISC-TEST"}
    normalized = decision_to_normalized_result(decision=decision, procurement=procurement)
    assert normalized["category_opportunities"] == []

    # Mimic: crm_ai_assessment_runner passes empty list to CandidatePolicy.
    policy_res = CandidatePolicy.calculate(
        route_profile="UNKNOWN",
        lifecycle="OPEN",
        item={"price": 10_000_000, "initial_price": 10_000_000},
        ai_result={
            "confidence": 0.5,
            "reasons": "v3_discovery",
            "category_opportunities": normalized["category_opportunities"],
        },
        cohort_median=5_000_000,
        egrz_info=None,
        business_scope_status="IN_PROFILE",
    )

    normalized_runtime: Dict[str, Any] = dict(normalized)
    normalized_runtime["category_opportunities"] = policy_res["category_opportunities"]

    producer = S13V2QueueProducer()
    out = producer._process_assessment(
        {
            "procurement_id": 999,
            "source_table": "reestr_contract_44_fz",
            "source_id": 1,
            "contract_number": "DISC-TEST",
            "assessment_id": 1,
            "candidate_level": None,
            "candidate_score": None,
            "normalized_result": normalized_runtime,
        },
        dry_run=True,
    )
    assert out is not None
    assert out["research_action"] == "LIGHT_RESEARCH"

