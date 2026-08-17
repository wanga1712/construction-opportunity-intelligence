"""CRM-V3-NO-COMMERCIAL-ENTRY-OUTPUT-CONTRACT-FIX-1 — normalizer/prompt/queue."""
from __future__ import annotations

from typing import Any, Dict

from src.services.commercial_routing_v3.normalizer import normalize_v3_output
from src.services.commercial_routing_v3.prompt import (
    PROMPT_VERSION,
    _CATEGORY_CODE_CONTRACT,
    build_v3_prompt,
    build_v3_prompt_from_model_input,
)
from src.services.commercial_routing_v3.queue_producer import CommercialRoutingV3QueueProducer
from src.services.commercial_routing_v3.research_queue_lifecycle import dry_run_research_admission


ALLOWED = {"lighting", "computers", "waterproofing", "flooring"}


def _norm(raw: Dict[str, Any]) -> Dict[str, Any]:
    return normalize_v3_output(
        raw,
        allowed_categories=ALLOWED,
        allowed_subcategories={c: set() for c in ALLOWED},
        has_okpd=True,
    )


def test_prompt_version_and_contract_text() -> None:
    assert PROMPT_VERSION == "v3_category_centric_routing_7b_v5"
    assert "NEVER put into category_code" in _CATEGORY_CODE_CONTRACT
    assert "gas meters" in _CATEGORY_CODE_CONTRACT
    assert "NO_COMMERCIAL_ENTRY" in _CATEGORY_CODE_CONTRACT
    proc = {
        "title": "Поставка счетчиков газа",
        "okpd_code": "26.51.63.110",
        "okpd_name": "Счетчики газа",
        "price": 1,
        "customer": "x",
        "law_type": "223-FZ",
        "source_table": "reestr_contract_223_fz",
        "region": "MO",
    }
    registry = [{"category_code": "lighting", "category_name": "Lighting", "lifecycle_state": "ACTIVE"}]
    p1 = build_v3_prompt(
        proc,
        registry=registry,
        okpd_priors=[],
        routing_signals=[],
        procurement_form_prior="DIRECT_GOODS_PURCHASE",
    )
    mi = {
        "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
        "procurement_id": 18215,
        "title": proc["title"],
        "okpd_codes": ["26.51.63.110"],
        "okpd_names": ["Счетчики газа"],
        "initial_price": 1,
        "customer_name": "x",
        "primary_commercial_region": "MO",
        "source_table": "reestr_contract_223_fz",
    }
    p2 = build_v3_prompt_from_model_input(
        mi,
        registry=registry,
        okpd_priors=[],
        procurement_form_prior="DIRECT_GOODS_PURCHASE",
    )
    for text in (p1, p2):
        assert "NEVER put into category_code" in text
        assert "empty_hypothesis_status=NO_COMMERCIAL_ENTRY" in text
        assert "overall_research_action=SKIP" in text
        assert "gas meters" in text


def test_case_a_canonical_nce() -> None:
    out = _norm(
        {
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "commercial_category_hypotheses": [],
            "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
            "overall_research_action": "SKIP",
            "discovery_required": False,
        }
    )
    assert out["commercial_category_hypotheses"] == []
    assert out["empty_hypothesis_status"] == "NO_COMMERCIAL_ENTRY"
    assert out["overall_research_action"] == "SKIP"
    assert out["discovery_required"] is False
    assert out["review_required"] is False


def test_case_b_18215_okpd_as_category_nce_track() -> None:
    out = _norm(
        {
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "commercial_category_hypotheses": [
                {
                    "category_code": "26.51.63.110",
                    "subcategory_code": "SUBCATEGORY_NOT_ASSIGNED",
                    "opportunity_track": "NO_COMMERCIAL_ENTRY",
                    "confidence": 0,
                    "research_action": "",
                    "candidate_medal": "WOOD",
                    "positive_evidence": [],
                    "negative_evidence": [],
                    "reason_codes": [],
                }
            ],
            "empty_hypothesis_status": None,
            "overall_research_action": "METADATA_ONLY",
            "discovery_required": False,
        }
    )
    assert "26.51.63.110" in out["rejected_category_codes"]
    assert out["commercial_category_hypotheses"] == []
    assert out["empty_hypothesis_status"] == "NO_COMMERCIAL_ENTRY"
    assert out["overall_research_action"] == "SKIP"
    assert out["discovery_required"] is False
    assert out["review_required"] is False


def test_case_c_invalid_commercial_hallucination() -> None:
    out = _norm(
        {
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "commercial_category_hypotheses": [
                {
                    "category_code": "26.51.63.110",
                    "opportunity_track": "DIRECT_SUPPLY",
                    "confidence": 0.8,
                    "positive_evidence": ["title"],
                    "research_action": "LIGHT_RESEARCH",
                    "candidate_medal": "BRONZE",
                }
            ],
        }
    )
    assert "26.51.63.110" in out["rejected_category_codes"]
    assert out["commercial_category_hypotheses"] == []
    assert out["empty_hypothesis_status"] == "REVIEW_REQUIRED"
    assert out["empty_hypothesis_status"] != "NO_COMMERCIAL_ENTRY"
    assert out["overall_research_action"] == "DISCOVER_COMMERCIAL_CATEGORY"
    assert out["discovery_required"] is True


def test_case_d_valid_registry_category_unaffected() -> None:
    out = _norm(
        {
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "commercial_category_hypotheses": [
                {
                    "category_code": "lighting",
                    "subcategory_code": "SUBCATEGORY_NOT_ASSIGNED",
                    "opportunity_track": "DIRECT_SUPPLY",
                    "confidence": 0.7,
                    "research_action": "LIGHT_RESEARCH",
                    "candidate_medal": "SILVER",
                    "positive_evidence": ["title_match"],
                    "reason_codes": ["title_match"],
                }
            ],
            "empty_hypothesis_status": None,
            "overall_research_action": "LIGHT_RESEARCH",
        }
    )
    assert len(out["commercial_category_hypotheses"]) == 1
    hyp = out["commercial_category_hypotheses"][0]
    assert hyp["category_code"] == "lighting"
    assert hyp["opportunity_track"] == "DIRECT_SUPPLY"
    assert out["empty_hypothesis_status"] is None
    assert out["overall_research_action"] == "LIGHT_RESEARCH"


def test_mixture_invalid_claim_and_nce_stays_review() -> None:
    out = _norm(
        {
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "commercial_category_hypotheses": [
                {
                    "category_code": "26.51.63.110",
                    "opportunity_track": "NO_COMMERCIAL_ENTRY",
                    "confidence": 0,
                },
                {
                    "category_code": "not_a_registry_cat",
                    "opportunity_track": "DIRECT_SUPPLY",
                    "confidence": 0.4,
                },
            ],
        }
    )
    assert out["empty_hypothesis_status"] == "REVIEW_REQUIRED"
    assert out["empty_hypothesis_status"] != "NO_COMMERCIAL_ENTRY"


def test_nce_queue_not_executable() -> None:
    p = CommercialRoutingV3QueueProducer(enabled=False)
    nce = {
        "procurement_form": "DIRECT_GOODS_PURCHASE",
        "commercial_category_hypotheses": [],
        "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
        "overall_research_action": "SKIP",
        "discovery_required": False,
        "review_required": False,
    }
    assert p.decide_from_normalized(nce) is None
    adm = dry_run_research_admission(
        procurement={
            "source_table": "reestr_contract_223_fz",
            "crm_stage": "torgi",
            "award_status": "submission_open",
            "end_date": "2099-01-01",
        },
        opportunity_track="NO_COMMERCIAL_ENTRY",
        discovery_required=False,
        review_required=False,
        has_valid_category=False,
        routed=True,
        research_action="SKIP",
    )
    assert adm.queue_eligible is False
    assert adm.research_purpose != "DISCOVER_COMMERCIAL_CATEGORY"
    assert adm.reason == "NO_COMMERCIAL_ENTRY"
