from __future__ import annotations

from src.services.candidate_policy import CandidatePolicy


def test_candidate_policy_does_not_inject_unknown_when_opps_empty_list() -> None:
    res = CandidatePolicy.calculate(
        route_profile="DIRECT_SUPPLY",
        lifecycle="OPEN",
        item={"price": 10_000_000, "initial_price": 10_000_000},
        ai_result={"confidence": 0.5, "reasons": "v3_discovery", "category_opportunities": []},
        cohort_median=5_000_000,
        egrz_info=None,
        business_scope_status="IN_PROFILE",
    )
    assert res["category_opportunities"] == []

