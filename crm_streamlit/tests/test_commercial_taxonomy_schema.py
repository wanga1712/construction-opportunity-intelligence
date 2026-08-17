"""Business semantic tests for COMMERCIAL-TAXONOMY-SCHEMA-AND-REGISTRY-1.

Uses in-memory fixtures mirroring commercial_taxonomy_seed_1.sql.
No production PostgreSQL required.
"""
from __future__ import annotations

from src.domain.commercial_taxonomy import (
    COMMERCIAL_KEEP_CODES,
    CONTEXT_ONLY_LEGACY_CODES,
    EvidenceRole,
    MATERIAL_ONLY_LEGACY_CODES,
    REDEFINED_LEGACY_CODES,
    TermSemanticType,
    is_valid_commercial_category_code,
)
from src.services.commercial_taxonomy_registry import classify_signal, normalize_term


DIMENSION_FIXTURES = [
    {
        "dimension_type": "WORK_METHOD",
        "dimension_code": "injection",
        "display_name": "Инъектирование",
        "normalized_term": "инъектирование",
        "term_semantic_type": "METHOD_TERM",
        "evidence_role": "SIGNAL_ONLY",
    },
    {
        "dimension_type": "APPLICATION_AREA",
        "dimension_code": "basement",
        "display_name": "Подвал",
        "normalized_term": "подвал",
        "term_semantic_type": "APPLICATION_AREA_TERM",
        "evidence_role": "SIGNAL_ONLY",
    },
    {
        "dimension_type": "APPLICATION_AREA",
        "dimension_code": "roof",
        "display_name": "Кровля",
        "normalized_term": "кровля",
        "term_semantic_type": "APPLICATION_AREA_TERM",
        "evidence_role": "SIGNAL_ONLY",
    },
    {
        "dimension_type": "BRAND",
        "dimension_code": "varton",
        "display_name": "ВАРТОН",
        "normalized_term": "вартон",
        "term_semantic_type": "BRAND_TERM",
        "evidence_role": "SIGNAL_ONLY",
    },
    {
        "dimension_type": "MATERIAL_FAMILY",
        "dimension_code": "frp_gfrp",
        "display_name": "Стеклопластик",
        "normalized_term": "стеклопластик",
        "term_semantic_type": "MATERIAL_TERM",
        "evidence_role": "SIGNAL_ONLY",
    },
]

SIGNAL_EXAMPLE_FIXTURES = [
    {
        "example_term": "ремонтный состав для бетона",
        "normalized_term": "ремонтный состав для бетона",
        "term_semantic_type": "PRODUCT_TERM",
        "evidence_role": "REQUIRE_CONTEXT",
        "dimension_type": None,
        "dimension_code": None,
        "commercial_category_code": "concrete_repair_materials",
        "commercial_subcategory_code": None,
        "is_commercial_category": True,
    },
    {
        "example_term": "инъекционная смола",
        "normalized_term": "инъекционная смола",
        "term_semantic_type": "PRODUCT_TERM",
        "evidence_role": "REQUIRE_CONTEXT",
        "dimension_type": None,
        "dimension_code": None,
        "commercial_category_code": "concrete_repair_materials",
        "commercial_subcategory_code": "injection_materials",
        "is_commercial_category": True,
    },
]


def _classify(term: str):
    return classify_signal(
        term,
        dimensions=DIMENSION_FIXTURES,
        signal_examples=SIGNAL_EXAMPLE_FIXTURES,
    )


class TestCommercialTaxonomySemantics:
    def test_injection_is_work_method_not_category(self) -> None:
        result = _classify("инъектирование")
        assert result is not None
        assert result.term_semantic_type == TermSemanticType.METHOD_TERM
        assert result.is_commercial_category is False
        assert result.commercial_category_code is None

    def test_basement_is_application_area_not_category(self) -> None:
        result = _classify("подвал")
        assert result is not None
        assert result.term_semantic_type == TermSemanticType.APPLICATION_AREA_TERM
        assert result.is_commercial_category is False

    def test_roof_is_application_area_not_waterproofing(self) -> None:
        result = _classify("кровля")
        assert result is not None
        assert result.term_semantic_type == TermSemanticType.APPLICATION_AREA_TERM
        assert result.commercial_category_code != "waterproofing"
        assert result.is_commercial_category is False

    def test_varton_is_brand_not_category(self) -> None:
        result = _classify("ВАРТОН")
        assert result is not None
        assert result.term_semantic_type == TermSemanticType.BRAND_TERM
        assert result.evidence_role == EvidenceRole.SIGNAL_ONLY
        assert result.is_commercial_category is False

    def test_frp_is_material_family_not_product_category(self) -> None:
        result = _classify("стеклопластик")
        assert result is not None
        assert result.term_semantic_type == TermSemanticType.MATERIAL_TERM
        assert result.is_commercial_category is False

    def test_concrete_repair_composition_maps_to_commercial_family(self) -> None:
        result = _classify("ремонтный состав для бетона")
        assert result is not None
        assert result.is_commercial_category is True
        assert result.commercial_category_code == "concrete_repair_materials"

    def test_injection_resin_maps_to_subcategory(self) -> None:
        result = _classify("инъекционная смола")
        assert result is not None
        assert result.commercial_category_code == "concrete_repair_materials"
        assert result.commercial_subcategory_code == "injection_materials"

    def test_unknown_is_not_valid_commercial_category_code(self) -> None:
        assert is_valid_commercial_category_code("UNKNOWN") is False
        assert is_valid_commercial_category_code("lighting") is True

    def test_legacy_code_partition_covers_all_14(self) -> None:
        all_legacy = (
            COMMERCIAL_KEEP_CODES
            | CONTEXT_ONLY_LEGACY_CODES
            | MATERIAL_ONLY_LEGACY_CODES
            | REDEFINED_LEGACY_CODES
        )
        assert len(all_legacy) == 14

    def test_normalize_term_lowercases_and_collapses_whitespace(self) -> None:
        assert normalize_term("  ВАРТОН  ") == "вартон"
        assert normalize_term("ремонтный   состав для бетона") == "ремонтный состав для бетона"
