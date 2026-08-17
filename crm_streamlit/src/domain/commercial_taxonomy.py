"""Commercial taxonomy domain types and validation helpers.

Schema-only layer for COMMERCIAL-TAXONOMY-SCHEMA-AND-REGISTRY-1.
Does not change AI or matcher runtime behavior.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Optional


class CategorySemanticType(StrEnum):
    COMMERCIAL_CATEGORY = "COMMERCIAL_CATEGORY"
    LEGACY_MIXED = "LEGACY_MIXED"
    CONTEXT_ONLY = "CONTEXT_ONLY"
    MATERIAL_ONLY = "MATERIAL_ONLY"


class CategoryLifecycleState(StrEnum):
    DRAFT = "DRAFT"
    REVIEW = "REVIEW"
    ACTIVE_AI_ONLY = "ACTIVE_AI_ONLY"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class SearchabilityMode(StrEnum):
    DIRECT_SEARCHABLE = "DIRECT_SEARCHABLE"
    FAMILY_ONLY = "FAMILY_ONLY"
    NOT_SEARCHABLE_BY_POLICY = "NOT_SEARCHABLE_BY_POLICY"


class LegacyCompatStrategy(StrEnum):
    KEEP_COMMERCIAL = "KEEP_COMMERCIAL"
    CONTEXT_ONLY = "CONTEXT_ONLY"
    MATERIAL_ONLY = "MATERIAL_ONLY"
    REDEFINED = "REDEFINED"


class DimensionType(StrEnum):
    MATERIAL_FAMILY = "MATERIAL_FAMILY"
    WORK_METHOD = "WORK_METHOD"
    APPLICATION_AREA = "APPLICATION_AREA"
    OBJECT_CONTEXT = "OBJECT_CONTEXT"
    MANUFACTURER = "MANUFACTURER"
    BRAND = "BRAND"
    MODEL = "MODEL"


class TermSemanticType(StrEnum):
    PRODUCT_TERM = "PRODUCT_TERM"
    MATERIAL_TERM = "MATERIAL_TERM"
    METHOD_TERM = "METHOD_TERM"
    APPLICATION_AREA_TERM = "APPLICATION_AREA_TERM"
    OBJECT_CONTEXT_TERM = "OBJECT_CONTEXT_TERM"
    MANUFACTURER_TERM = "MANUFACTURER_TERM"
    BRAND_TERM = "BRAND_TERM"
    MODEL_TERM = "MODEL_TERM"
    ATTRIBUTE_TERM = "ATTRIBUTE_TERM"
    STOP_TERM = "STOP_TERM"
    AMBIGUOUS_TERM = "AMBIGUOUS_TERM"


class EvidenceRole(StrEnum):
    DIRECT_CATEGORY_EVIDENCE = "DIRECT_CATEGORY_EVIDENCE"
    REQUIRE_CONTEXT = "REQUIRE_CONTEXT"
    SIGNAL_ONLY = "SIGNAL_ONLY"
    NEGATIVE = "NEGATIVE"
    STOP = "STOP"


class SubcategorySemanticType(StrEnum):
    COMMERCIAL_SUBCATEGORY = "COMMERCIAL_SUBCATEGORY"
    INJECTION_MATERIALS = "INJECTION_MATERIALS"
    CONCRETE_REPAIR_MATERIALS = "CONCRETE_REPAIR_MATERIALS"


@dataclass(frozen=True)
class SignalClassification:
    """Result of classifying a free-text signal against taxonomy dimensions."""

    normalized_term: str
    term_semantic_type: TermSemanticType
    evidence_role: EvidenceRole
    dimension_type: Optional[DimensionType]
    dimension_code: Optional[str]
    is_commercial_category: bool
    commercial_category_code: Optional[str] = None
    commercial_subcategory_code: Optional[str] = None


def is_valid_commercial_category_code(category_code: str) -> bool:
    """UNKNOWN is never a valid commercial category code."""
    return bool(category_code) and category_code.upper() != "UNKNOWN"


COMMERCIAL_KEEP_CODES = frozenset(
    {
        "cable_support_systems",
        "composite_structures",
        "computers",
        "curbstone",
        "drainage_water_management",
        "flooring",
        "lighting",
        "waterproofing",
    }
)

CONTEXT_ONLY_LEGACY_CODES = frozenset(
    {
        "bridge_road_infrastructure",
        "external_utility_networks",
    }
)

MATERIAL_ONLY_LEGACY_CODES = frozenset({"composites"})

REDEFINED_LEGACY_CODES = frozenset(
    {
        "concrete_materials",
        "structural_reinforcement",
        "waterproofing_concrete_repair",
    }
)

TARGET_COMMERCIAL_CODES = frozenset(COMMERCIAL_KEEP_CODES | {"concrete_repair_materials"})
