"""Commercial routing V3 domain types.

Candidate Medal scope:
  procurement + commercial_category + commercial_subcategory + opportunity_track

Medal is evaluated WITHIN opportunity_track, not as absolute procurement rank.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Dict, List, Optional


ROUTING_VERSION = "v3"
PROMPT_VERSION = "v3_category_centric_routing_7b_v5"


class SourceContour(StrEnum):
    PUBLIC_44FZ = "PUBLIC_44FZ"
    CORPORATE_223FZ = "CORPORATE_223FZ"
    UNKNOWN = "UNKNOWN"


class ProcurementForm(StrEnum):
    DIRECT_GOODS_PURCHASE = "DIRECT_GOODS_PURCHASE"
    CONSTRUCTION_WORKS = "CONSTRUCTION_WORKS"
    DESIGN_AND_BUILD = "DESIGN_AND_BUILD"
    DESIGN_EXPERTISE_AND_BUILD = "DESIGN_EXPERTISE_AND_BUILD"
    DESIGN_ONLY = "DESIGN_ONLY"
    SURVEY_AND_DESIGN = "SURVEY_AND_DESIGN"
    WORKS_OTHER = "WORKS_OTHER"
    SERVICES_OTHER = "SERVICES_OTHER"
    UNKNOWN = "UNKNOWN"


class AnalysisMode(StrEnum):
    DIRECT_PRODUCT = "DIRECT_PRODUCT"
    EMBEDDED_MATERIAL_DISCOVERY = "EMBEDDED_MATERIAL_DISCOVERY"
    FUTURE_REQUIREMENT_DISCOVERY = "FUTURE_REQUIREMENT_DISCOVERY"
    GENERAL_DISCOVERY = "GENERAL_DISCOVERY"


class OpportunityTrack(StrEnum):
    """Commercial scenario axis — NOT subcategory."""

    DIRECT_SUPPLY = "DIRECT_SUPPLY"
    EMBEDDED_MATERIAL = "EMBEDDED_MATERIAL"
    DESIGN_REQUIREMENT = "DESIGN_REQUIREMENT"
    DESIGN_INFLUENCE = "DESIGN_INFLUENCE"
    NO_COMMERCIAL_ENTRY = "NO_COMMERCIAL_ENTRY"
    UNKNOWN = "UNKNOWN"


class ResearchAction(StrEnum):
    SKIP = "SKIP"
    METADATA_ONLY = "METADATA_ONLY"
    LIGHT_RESEARCH = "LIGHT_RESEARCH"
    PRIORITY_DOCS = "PRIORITY_DOCS"
    DEEP_RESEARCH = "DEEP_RESEARCH"
    DISCOVER_COMMERCIAL_CATEGORY = "DISCOVER_COMMERCIAL_CATEGORY"


class CandidateMedal(StrEnum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    BRONZE = "BRONZE"
    WOOD = "WOOD"


class CategoryValueBasis(StrEnum):
    DIRECT_PROCUREMENT_VALUE = "DIRECT_PROCUREMENT_VALUE"
    FUTURE_REQUIREMENT = "FUTURE_REQUIREMENT"
    UNKNOWN_ADDRESSABLE_VALUE = "UNKNOWN_ADDRESSABLE_VALUE"
    DOCUMENT_EVIDENCE = "DOCUMENT_EVIDENCE"


class OkpdMatchType(StrEnum):
    EXACT = "EXACT"
    PREFIX = "PREFIX"


class RoutingSignalType(StrEnum):
    POSITIVE_SIGNAL = "POSITIVE_SIGNAL"
    NEGATIVE_SIGNAL = "NEGATIVE_SIGNAL"
    HARD_EXCLUSION = "HARD_EXCLUSION"
    CONTEXT_SIGNAL = "CONTEXT_SIGNAL"


class RoutingSignalScope(StrEnum):
    PRELIMINARY_TITLE = "PRELIMINARY_TITLE"
    PRELIMINARY_OKPD = "PRELIMINARY_OKPD"
    OTHER_METADATA = "OTHER_METADATA"


class LegacyOkpdMigrationClass(StrEnum):
    MIGRATE_CONFIDENT = "MIGRATE_CONFIDENT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    OBSOLETE = "OBSOLETE"
    NEGATIVE_SIGNAL = "NEGATIVE_SIGNAL"
    CONTEXT_ONLY = "CONTEXT_ONLY"


PROCUREMENT_FORM_DEFAULT_ANALYSIS: dict[ProcurementForm, list[AnalysisMode]] = {
    ProcurementForm.DIRECT_GOODS_PURCHASE: [AnalysisMode.DIRECT_PRODUCT],
    ProcurementForm.CONSTRUCTION_WORKS: [AnalysisMode.EMBEDDED_MATERIAL_DISCOVERY],
    ProcurementForm.DESIGN_ONLY: [AnalysisMode.FUTURE_REQUIREMENT_DISCOVERY],
    ProcurementForm.SURVEY_AND_DESIGN: [AnalysisMode.FUTURE_REQUIREMENT_DISCOVERY],
    ProcurementForm.DESIGN_AND_BUILD: [
        AnalysisMode.FUTURE_REQUIREMENT_DISCOVERY,
        AnalysisMode.EMBEDDED_MATERIAL_DISCOVERY,
    ],
    ProcurementForm.DESIGN_EXPERTISE_AND_BUILD: [
        AnalysisMode.FUTURE_REQUIREMENT_DISCOVERY,
        AnalysisMode.EMBEDDED_MATERIAL_DISCOVERY,
    ],
    ProcurementForm.WORKS_OTHER: [AnalysisMode.GENERAL_DISCOVERY],
    ProcurementForm.SERVICES_OTHER: [AnalysisMode.GENERAL_DISCOVERY],
    ProcurementForm.UNKNOWN: [AnalysisMode.GENERAL_DISCOVERY],
}

TRACKS_FOR_FORM: dict[ProcurementForm, list[OpportunityTrack]] = {
    ProcurementForm.DIRECT_GOODS_PURCHASE: [OpportunityTrack.DIRECT_SUPPLY],
    ProcurementForm.CONSTRUCTION_WORKS: [OpportunityTrack.EMBEDDED_MATERIAL],
    ProcurementForm.DESIGN_ONLY: [
        OpportunityTrack.DESIGN_REQUIREMENT,
        OpportunityTrack.DESIGN_INFLUENCE,
    ],
    ProcurementForm.SURVEY_AND_DESIGN: [
        OpportunityTrack.DESIGN_REQUIREMENT,
        OpportunityTrack.DESIGN_INFLUENCE,
    ],
    ProcurementForm.DESIGN_AND_BUILD: [
        OpportunityTrack.DESIGN_REQUIREMENT,
        OpportunityTrack.EMBEDDED_MATERIAL,
        OpportunityTrack.DESIGN_INFLUENCE,
    ],
    ProcurementForm.DESIGN_EXPERTISE_AND_BUILD: [
        OpportunityTrack.DESIGN_REQUIREMENT,
        OpportunityTrack.EMBEDDED_MATERIAL,
        OpportunityTrack.DESIGN_INFLUENCE,
    ],
}


@dataclass
class CategoryOpportunityV3:
    commercial_category_code: str
    commercial_subcategory_code: Optional[str]
    opportunity_track: OpportunityTrack
    category_confidence: float
    research_action: ResearchAction
    research_priority: int
    commercial_priority_score: int
    research_value_score: int
    candidate_medal: CandidateMedal
    expected_category_value: Optional[float]
    category_value_basis: CategoryValueBasis
    reason_codes: List[str] = field(default_factory=list)
    positive_evidence: List[str] = field(default_factory=list)
    negative_evidence: List[str] = field(default_factory=list)


@dataclass
class RoutingDecisionV3:
    source_contour: SourceContour
    procurement_form: ProcurementForm
    analysis_modes: List[AnalysisMode]
    object_context: List[str] = field(default_factory=list)
    material_signals: List[str] = field(default_factory=list)
    work_methods: List[str] = field(default_factory=list)
    application_areas: List[str] = field(default_factory=list)
    brands: List[str] = field(default_factory=list)
    commercial_category_hypotheses: List[CategoryOpportunityV3] = field(default_factory=list)
    discovery_required: bool = False
    overall_research_action: ResearchAction = ResearchAction.SKIP
    registry_version: int = 1
    registry_hash: str = ""
    prompt_version: str = PROMPT_VERSION
    routing_version: str = ROUTING_VERSION
    model_name: str = ""
    empty_hypothesis_status: Optional[str] = None
    empty_hypothesis_reason_codes: List[str] = field(default_factory=list)
    rejected_category_codes: List[str] = field(default_factory=list)
    preferred_opportunity_track: Optional[str] = None
    review_required: bool = False
    routing_mode: Optional[str] = None
    object_classification: Optional[Dict[str, Any]] = None
    document_research_priority: List[str] = field(default_factory=list)
    hypothesis_details: List[Dict[str, Any]] = field(default_factory=list)
    awarded_context: Optional[Dict[str, Any]] = None
    post_award_commercial_target: Optional[str] = None
    post_award_commercial_target_name: Optional[str] = None

    def to_normalized_dict(self) -> Dict[str, Any]:
        return {
            "routing_version": self.routing_version,
            "source_contour": self.source_contour.value,
            "procurement_form": self.procurement_form.value,
            "analysis_modes": [m.value for m in self.analysis_modes],
            "object_context": self.object_context,
            "material_signals": self.material_signals,
            "work_methods": self.work_methods,
            "application_areas": self.application_areas,
            "brands": self.brands,
            "commercial_category_hypotheses": [
                {
                    "category_code": h.commercial_category_code,
                    "subcategory_code": h.commercial_subcategory_code,
                    "opportunity_track": h.opportunity_track.value,
                    "confidence": h.category_confidence,
                    "research_action": h.research_action.value,
                    "research_priority": h.research_priority,
                    "commercial_priority_score": h.commercial_priority_score,
                    "research_value_score": h.research_value_score,
                    "candidate_medal": h.candidate_medal.value,
                    "expected_category_value": h.expected_category_value,
                    "category_value_basis": h.category_value_basis.value,
                    "reason_codes": h.reason_codes,
                    "positive_evidence": h.positive_evidence,
                    "negative_evidence": h.negative_evidence,
                }
                for h in self.commercial_category_hypotheses
            ],
            "discovery_required": self.discovery_required,
            "overall_research_action": self.overall_research_action.value,
            "empty_hypothesis_status": self.empty_hypothesis_status,
            "routing_mode": self.routing_mode,
            "object_classification": self.object_classification,
            "document_research_priority": self.document_research_priority,
            "hypothesis_details": self.hypothesis_details,
            "registry_version": self.registry_version,
            "registry_hash": self.registry_hash,
            "prompt_version": self.prompt_version,
            "model_name": self.model_name,
        }
