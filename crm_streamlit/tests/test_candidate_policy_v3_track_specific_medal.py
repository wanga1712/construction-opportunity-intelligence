from __future__ import annotations

from src.services.candidate_policy import CandidatePolicy


def test_candidate_policy_reuses_opportunity_specific_candidate_level() -> None:
    ai_result = {
        "confidence": 0.9,
        "reasons": "v3_track_specific",
        "category_opportunities": [
            {
                "category_code": "lighting",
                "subcategory_code": None,
                "opportunity_track": "DIRECT_SUPPLY",
                "candidate_level": "GOLD",
                "candidate_score": 88.0,
                "research_action": "PRIORITY_DOCS",
            },
            {
                "category_code": "lighting",
                "subcategory_code": None,
                "opportunity_track": "EMBEDDED_MATERIAL",
                "candidate_level": "SILVER",
                "candidate_score": 66.0,
                "research_action": "LIGHT_RESEARCH",
            },
        ],
    }

    res = CandidatePolicy.calculate(
        route_profile="DIRECT_SUPPLY",
        lifecycle="OPEN",
        item={"price": 10_000_000, "initial_price": 10_000_000},
        ai_result=ai_result,
        cohort_median=5_000_000,
        egrz_info=None,
        business_scope_status="IN_PROFILE",
    )
    processed = res["category_opportunities"]
    assert len(processed) == 2

    by_track = {o.get("opportunity_track"): o for o in processed}
    assert by_track["DIRECT_SUPPLY"]["candidate_level"] == "GOLD"
    assert by_track["EMBEDDED_MATERIAL"]["candidate_level"] == "SILVER"
    assert by_track["DIRECT_SUPPLY"]["candidate_score"] == 88.0
    assert by_track["EMBEDDED_MATERIAL"]["candidate_score"] == 66.0

