from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from src.domain.commercial_routing_v3 import AnalysisMode, ProcurementForm, SourceContour
from src.services.commercial_routing_v3.engine import CommercialRoutingV3Engine
from src.services.commercial_routing_v3.runtime_adapter import (
    decision_to_normalized_result,
)


class _EnumBox:
    def __init__(self, value: Any):
        self.value = value


def test_adapter_dataclass_path_preserves_v3_keys() -> None:
    engine = CommercialRoutingV3Engine(crm_db=None)
    procurement: Dict[str, Any] = {
        "source_table": "reestr_contract_44_fz",
        "source_id": 1,
        "contract_number": "DL-1",
        "law_type": "44_FZ",
        "title": "Поставка светильников",
        "okpd_code": "42.11.20.900",
        "okpd_name": "Светильники",
        "price": 10_000_000,
        "customer": "X",
        "region": "MOW",
    }
    decision = engine.route_deterministic(procurement)
    normalized = decision_to_normalized_result(decision=decision, procurement=procurement)

    assert normalized["discovery_required"] is False
    assert normalized["source_contour"] == SourceContour.PUBLIC_44FZ.value
    assert normalized["procurement_form"] == ProcurementForm.DIRECT_GOODS_PURCHASE.value
    assert normalized["analysis_mode"] is not None

    opps: List[Dict[str, Any]] = normalized["category_opportunities"]
    assert opps, "expected at least one hypothesis for lighting fixture"

    required_opp_keys = {
        "category_code",
        "subcategory_code",
        "confidence",
        "opportunity_track",
        "research_action",
        "commercial_priority_score",
        "research_value_score",
        "candidate_medal",
        "reason_codes",
        "negative_evidence",
    }
    assert required_opp_keys.issubset(set(opps[0].keys()))


def test_adapter_dict_path_and_discovery_false() -> None:
    decision = {
        "source_contour": SourceContour.PUBLIC_44FZ,
        "procurement_form": ProcurementForm.DIRECT_GOODS_PURCHASE,
        "analysis_modes": [AnalysisMode.DIRECT_PRODUCT],
        "discovery_required": False,
        "overall_research_action": "LIGHT_RESEARCH",
        "registry_version": 3,
        "registry_hash": "hash-1",
        "prompt_version": "p-1",
        "routing_version": "v3",
        "model_name": "qwen2.5:7b",
        "commercial_category_hypotheses": [
            {
                "commercial_category_code": "lighting",
                "commercial_subcategory_code": None,
                "opportunity_track": "DIRECT_SUPPLY",
                "category_confidence": 0.9,
                "research_action": "PRIORITY_DOCS",
                "research_priority": 10,
                "commercial_priority_score": 80,
                "research_value_score": 70,
                "candidate_medal": "GOLD",
                "expected_category_value": 123.0,
                "category_value_basis": "DIRECT_PROCUREMENT_VALUE",
                "reason_codes": ["okpd_prior"],
                "positive_evidence": ["светильник"],
                "negative_evidence": ["отопление"],
            }
        ],
    }

    procurement = {"contract_number": "D-1"}
    normalized = decision_to_normalized_result(decision=decision, procurement=procurement)

    assert normalized["discovery_required"] is False
    assert normalized["source_contour"] == SourceContour.PUBLIC_44FZ.value
    assert normalized["procurement_form"] == ProcurementForm.DIRECT_GOODS_PURCHASE.value
    assert normalized["analysis_mode"] == AnalysisMode.DIRECT_PRODUCT.value
    assert normalized["category_opportunities"][0]["candidate_medal"] == "GOLD"
    assert normalized["category_opportunities"][0]["negative_evidence"] == ["отопление"]


def test_adapter_discovery_true_false_paths() -> None:
    decision_true = {
        "source_contour": SourceContour.PUBLIC_44FZ,
        "procurement_form": ProcurementForm.CONSTRUCTION_WORKS,
        "analysis_modes": [AnalysisMode.EMBEDDED_MATERIAL_DISCOVERY],
        "discovery_required": True,
        "overall_research_action": "LIGHT_RESEARCH",
        "registry_version": 1,
        "registry_hash": "",
        "prompt_version": "",
        "routing_version": "v3",
        "model_name": "",
        "commercial_category_hypotheses": [],
    }
    normalized_true = decision_to_normalized_result(decision=decision_true, procurement={})
    assert normalized_true["discovery_required"] is True

    decision_false = dict(decision_true)
    decision_false["discovery_required"] = False
    normalized_false = decision_to_normalized_result(decision=decision_false, procurement={})
    assert normalized_false["discovery_required"] is False

