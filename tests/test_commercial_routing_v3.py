"""Regression tests for COMMERCIAL-ROUTING-V3-CORE-IMPLEMENTATION-1.

Medal invariant: evaluated WITHIN opportunity_track.
Procurement total alone cannot cause GOLD.
"""
from __future__ import annotations

from src.domain.commercial_routing_v3 import (
    AnalysisMode,
    CandidateMedal,
    CategoryValueBasis,
    OpportunityTrack,
    ProcurementForm,
    ResearchAction,
    SourceContour,
)
from src.services.commercial_routing_v3.engine import CommercialRoutingV3Engine
from src.services.commercial_routing_v3.medal import TrackMedalInput, compute_track_medal
from src.services.commercial_routing_v3.procurement_form import classify_procurement_form
from src.services.commercial_routing_v3.queue_producer import CommercialRoutingV3QueueProducer
from src.services.commercial_routing_v3.source_contour import resolve_source_contour


def _route(procurement: dict):
    return CommercialRoutingV3Engine().route_deterministic(procurement)


class TestSourceContour:
    def test_44fz(self) -> None:
        assert resolve_source_contour(source_table="reestr_contract_44_fz", law_type="44_FZ") == SourceContour.PUBLIC_44FZ

    def test_223fz(self) -> None:
        assert resolve_source_contour(source_table="reestr_contract_223_fz", law_type="223_FZ") == SourceContour.CORPORATE_223FZ


class TestProcurementForm:
    def test_direct_lighting_despite_building_okpd(self) -> None:
        form = classify_procurement_form({
            "title": "Поставка светильников для административного здания",
            "okpd_code": "42.11.20.900",
            "okpd_name": "Работы строительные",
        })
        assert form == ProcurementForm.DIRECT_GOODS_PURCHASE

    def test_construction_from_title(self) -> None:
        form = classify_procurement_form({
            "title": "Строительство пешеходного перехода",
            "okpd_code": "42.11.20.900",
        })
        assert form == ProcurementForm.CONSTRUCTION_WORKS

    def test_design_only(self) -> None:
        form = classify_procurement_form({
            "title": "Разработка проектной документации на реконструкцию",
            "okpd_code": "71.11.12",
        })
        assert form == ProcurementForm.DESIGN_ONLY


class TestTrackMedal:
    def test_low_value_direct_can_gold(self) -> None:
        medal, _, _ = compute_track_medal(
            TrackMedalInput(
                opportunity_track=OpportunityTrack.DIRECT_SUPPLY,
                procurement_form=ProcurementForm.DIRECT_GOODS_PURCHASE,
                category_confidence=0.9,
                evidence_strength=80,
                entry_feasibility=70,
                value_clarity=85,
                procurement_total=300_000,
                has_direct_value_basis=True,
                has_non_price_evidence=True,
            )
        )
        assert medal == CandidateMedal.GOLD

    def test_procurement_total_alone_cannot_cause_gold(self) -> None:
        medal, _, _ = compute_track_medal(
            TrackMedalInput(
                opportunity_track=OpportunityTrack.EMBEDDED_MATERIAL,
                procurement_form=ProcurementForm.CONSTRUCTION_WORKS,
                category_confidence=0.3,
                evidence_strength=10,
                entry_feasibility=20,
                value_clarity=90,
                procurement_total=800_000_000,
                has_direct_value_basis=False,
                has_non_price_evidence=False,
            )
        )
        assert medal != CandidateMedal.GOLD

    def test_embedded_material_can_gold_with_evidence(self) -> None:
        medal, _, _ = compute_track_medal(
            TrackMedalInput(
                opportunity_track=OpportunityTrack.EMBEDDED_MATERIAL,
                procurement_form=ProcurementForm.CONSTRUCTION_WORKS,
                category_confidence=0.75,
                evidence_strength=85,
                entry_feasibility=80,
                value_clarity=20,
                procurement_total=800_000_000,
                has_direct_value_basis=False,
                has_non_price_evidence=True,
            )
        )
        assert medal == CandidateMedal.GOLD

    def test_design_requirement_can_gold(self) -> None:
        medal, _, _ = compute_track_medal(
            TrackMedalInput(
                opportunity_track=OpportunityTrack.DESIGN_REQUIREMENT,
                procurement_form=ProcurementForm.DESIGN_ONLY,
                category_confidence=0.8,
                evidence_strength=80,
                entry_feasibility=75,
                value_clarity=10,
                procurement_total=15_000_000,
                has_non_price_evidence=True,
            )
        )
        assert medal == CandidateMedal.GOLD

    def test_gold_is_track_specific(self) -> None:
        base = dict(
            procurement_form=ProcurementForm.CONSTRUCTION_WORKS,
            category_confidence=0.85,
            evidence_strength=90,
            entry_feasibility=80,
            value_clarity=20,
            procurement_total=500_000_000,
            has_non_price_evidence=True,
        )
        m_embedded, _, _ = compute_track_medal(
            TrackMedalInput(opportunity_track=OpportunityTrack.EMBEDDED_MATERIAL, **base)
        )
        m_design, _, _ = compute_track_medal(
            TrackMedalInput(
                opportunity_track=OpportunityTrack.DESIGN_REQUIREMENT,
                procurement_form=ProcurementForm.CONSTRUCTION_WORKS,
                category_confidence=0.5,
                evidence_strength=40,
                entry_feasibility=40,
                value_clarity=20,
                procurement_total=500_000_000,
                has_non_price_evidence=True,
            )
        )
        assert m_embedded == CandidateMedal.GOLD
        assert m_design != CandidateMedal.GOLD


class TestRoutingEngine:
    def test_construction_multi_category_priors(self) -> None:
        decision = _route({
            "title": "Строительство пешеходного перехода",
            "okpd_code": "42.11.20.900",
            "okpd_name": "Работы строительные по строительству улично-дорожной сети",
            "source_table": "reestr_contract_44_fz_awarded",
            "law_type": "44_FZ",
            "price": 50_000_000,
        })
        cats = {h.commercial_category_code for h in decision.commercial_category_hypotheses}
        assert len(cats) >= 2
        assert decision.procurement_form == ProcurementForm.CONSTRUCTION_WORKS
        assert AnalysisMode.EMBEDDED_MATERIAL_DISCOVERY in decision.analysis_modes

    def test_procurement_1282_not_direct_goods(self) -> None:
        decision = _route({
            "title": "Проектно-изыскательские работы и строительство пешеходного перехода",
            "okpd_code": "42.11.20.900",
            "okpd_name": "Работы строительные по строительству улично-дорожной сети",
            "source_table": "reestr_contract_44_fz_awarded",
            "law_type": "44_FZ",
            "price": 100_000_000,
        })
        assert decision.procurement_form != ProcurementForm.DIRECT_GOODS_PURCHASE

    def test_design_only_discovery_without_categories(self) -> None:
        decision = _route({
            "title": "Разработка проектной документации",
            "okpd_code": "71.11.12",
            "source_table": "reestr_contract_44_fz",
            "law_type": "44_FZ",
        })
        assert decision.procurement_form == ProcurementForm.DESIGN_ONLY
        assert decision.discovery_required is True
        assert decision.overall_research_action != ResearchAction.SKIP

    def test_no_category_discovery_route(self) -> None:
        producer = CommercialRoutingV3QueueProducer()
        decision = {
            "commercial_category_hypotheses": [],
            "discovery_required": True,
            "overall_research_action": "LIGHT_RESEARCH",
            "analysis_modes": ["FUTURE_REQUIREMENT_DISCOVERY"],
            "routing_version": "v3",
        }
        q = producer.decide_from_normalized(decision)
        assert q is not None
        assert q["research_action"] == "LIGHT_RESEARCH"

    def test_category_value_not_procurement_total_for_construction(self) -> None:
        decision = _route({
            "title": "Строительство дороги",
            "okpd_code": "42.11.20.900",
            "price": 800_000_000,
            "law_type": "44_FZ",
            "source_table": "reestr_contract_44_fz",
        })
        for h in decision.commercial_category_hypotheses:
            if h.opportunity_track == OpportunityTrack.EMBEDDED_MATERIAL:
                assert h.category_value_basis != CategoryValueBasis.DIRECT_PROCUREMENT_VALUE
                assert h.expected_category_value is None

    def test_stop_word_negative_not_hard_skip(self) -> None:
        decision = _route({
            "title": "Поставка светильников с отоплением в комплекте здания",
            "okpd_code": "27.40.11",
            "law_type": "44_FZ",
            "source_table": "reestr_contract_44_fz",
            "price": 500_000,
        })
        assert decision.procurement_form == ProcurementForm.DIRECT_GOODS_PURCHASE
        assert decision.overall_research_action != ResearchAction.SKIP

    def test_opportunity_track_on_hypotheses(self) -> None:
        decision = _route({
            "title": "Поставка светильников уличного освещения",
            "okpd_code": "27.40.32",
            "law_type": "44_FZ",
            "source_table": "reestr_contract_44_fz",
            "price": 300_000,
        })
        tracks = {h.opportunity_track for h in decision.commercial_category_hypotheses}
        assert OpportunityTrack.DIRECT_SUPPLY in tracks or not decision.commercial_category_hypotheses
