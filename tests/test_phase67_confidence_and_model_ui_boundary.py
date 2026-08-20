from __future__ import annotations

from src.services.candidate_policy import CandidatePolicy
from src.ui.components.analytics_v2.card_tabs_ai_readonly import is_model_hypothesis_opp


def test_confidence_zero_is_preserved_in_candidate_policy() -> None:
    # Regression for `float(x or 1.0)`-style truthiness bugs:
    # if confidence is explicitly 0.0, candidate_score must stay 0.0.
    item = {"price": 100_000, "initial_price": 100_000}
    opp = {
        "confidence": 0.0,
        "opportunity_status": "POSSIBLE",
        "expected_volume": "HIGH",
    }
    res = CandidatePolicy.calculate_opportunity(
        route_profile="DIRECT_SUPPLY",
        lifecycle="OPEN",
        item=item,
        egrz_info=None,
        cohort_median=5_000_000.0,
        opp=opp,
    )
    assert res["candidate_score"] == 0.0
    assert res["candidate_level"] == "WOOD"


def test_object_mode_contextual_priors_are_not_ui_model_hypotheses() -> None:
    model_opp = {"reason_codes": ["track_coerced_by_form"]}
    contextual_opp = {"reason_codes": ["object_mode_contextual_prior", "requires_document_confirmation"]}

    assert is_model_hypothesis_opp(model_opp) is True
    assert is_model_hypothesis_opp(contextual_opp) is False

