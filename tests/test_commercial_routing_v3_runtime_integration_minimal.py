from __future__ import annotations

from typing import Any, Dict, List

from src.services.commercial_routing_v3.engine import CommercialRoutingV3Engine
from src.services.commercial_routing_v3.runtime_adapter import decision_to_normalized_result
from src.services.commercial_routing_v3.opportunity_lifecycle_sync import (
    compute_opportunity_lifecycle_updates,
)
from src.services.s13_v2_queue_producer import S13V2QueueProducer


def _best_hypothesis(decision: Any) -> Dict[str, Any]:
    hyps = decision.commercial_category_hypotheses or []
    # Prefer highest commercial_priority_score.
    def score(h: Any) -> float:
        return float(getattr(h, "commercial_priority_score", 0) or 0)

    hyps_sorted = sorted(hyps, key=score, reverse=True)
    h0 = hyps_sorted[0] if hyps_sorted else None
    if h0 is None:
        return {}
    return {
        "category_code": getattr(h0, "commercial_category_code", None),
        "track": getattr(getattr(h0, "opportunity_track", None), "value", None)
        or getattr(h0, "opportunity_track", None),
    }


def test_direct_lighting_44fz_best_is_lighting() -> None:
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
    best = _best_hypothesis(decision)

    assert best["category_code"] == "lighting"
    assert decision.procurement_form.value == "DIRECT_GOODS_PURCHASE"
    assert any(
        getattr(h, "opportunity_track").value == "DIRECT_SUPPLY"
        for h in decision.commercial_category_hypotheses or []
    )


def test_direct_computers_44fz_produces_direct_supply() -> None:
    engine = CommercialRoutingV3Engine(crm_db=None)
    procurement: Dict[str, Any] = {
        "source_table": "reestr_contract_44_fz",
        "source_id": 2,
        "contract_number": "PC-2",
        "law_type": "44_FZ",
        "title": "Поставка персональных компьютеров",
        "okpd_code": "26.20",
        "okpd_name": "Компьютеры",
        "price": 12_000_000,
        "customer": "X",
        "region": "MOW",
    }
    decision = engine.route_deterministic(procurement)
    assert decision.procurement_form.value == "DIRECT_GOODS_PURCHASE"
    assert any(
        getattr(h, "commercial_category_code", None) == "computers"
        for h in decision.commercial_category_hypotheses or []
    )
    assert any(
        getattr(h, "opportunity_track").value == "DIRECT_SUPPLY"
        for h in decision.commercial_category_hypotheses or []
    )


def test_zero_hypotheses_discovery_required_allows_queue_discovery() -> None:
    engine = CommercialRoutingV3Engine(crm_db=None)
    producer = S13V2QueueProducer()

    procurement: Dict[str, Any] = {
        "source_table": "reestr_contract_44_fz",
        "source_id": 3,
        "contract_number": "DISC-3",
        "law_type": "44_FZ",
        "title": "Разработка проект",
        # Unknown okpd => no default priors match
        "okpd_code": "99.99.99",
        "okpd_name": "Неизвестный продукт",
        "price": 8_000_000,
        "customer": "X",
        "region": "MOW",
    }
    decision = engine.route_deterministic(procurement)
    assert decision.discovery_required is True
    assert len(decision.commercial_category_hypotheses or []) == 0

    normalized = decision_to_normalized_result(decision=decision, procurement=procurement)

    out = producer._process_assessment(
        {
            "procurement_id": 3,
            "source_table": procurement["source_table"],
            "source_id": procurement["source_id"],
            "contract_number": procurement["contract_number"],
            "assessment_id": 10,
            "candidate_level": None,
            "candidate_score": None,
            "normalized_result": normalized,
        },
        dry_run=True,
    )
    assert out is not None
    assert out["research_action"] == "LIGHT_RESEARCH"


def test_lifecycle_awarded_transitions_are_track_specific() -> None:
    # OPEN/WAITING logic is already covered elsewhere; here we ensure AWARDED transitions.
    src_procurements: List[Dict[str, Any]] = [
        {
            "procurement_id": 100,
            "source_table": "reestr_contract_44_fz_awarded",
            "law_type": "44_FZ",
            "contract_number": "CN-100",
            "crm_stage": "razygranye",
            "award_status": "awarded",
        }
    ]

    opps = [
        {
            "id": 1,
            "procurement_id": 100,
            "commercial_category_code": "lighting",
            "commercial_subcategory_code": None,
            "opportunity_track": "DIRECT_SUPPLY",
            "commercial_state": "ACTIVE",
            "last_source_event": "OPEN",
        },
        {
            "id": 2,
            "procurement_id": 100,
            "commercial_category_code": "waterproofing",
            "commercial_subcategory_code": None,
            "opportunity_track": "EMBEDDED_MATERIAL",
            "commercial_state": "ACTIVE",
            "last_source_event": "OPEN",
        },
        {
            "id": 3,
            "procurement_id": 100,
            "commercial_category_code": "waterproofing",
            "commercial_subcategory_code": None,
            "opportunity_track": "DESIGN_REQUIREMENT",
            "commercial_state": "ACTIVE",
            "last_source_event": "OPEN",
        },
    ]

    updated, _audit = compute_opportunity_lifecycle_updates(
        source_procurements=src_procurements,
        opportunities=opps,
        existing_audit=[],
    )

    by_id = {o["id"]: o for o in updated}
    assert by_id[1]["commercial_state"] == "CLOSED"
    assert by_id[2]["commercial_state"] == "FOLLOW_UP_AWARDED"
    assert by_id[3]["commercial_state"] == "FOLLOW_UP_AWARDED"

