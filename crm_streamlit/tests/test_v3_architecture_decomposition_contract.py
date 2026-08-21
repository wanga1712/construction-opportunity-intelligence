"""Architecture decomposition contract tests (no live Ollama)."""
from __future__ import annotations

from src.services.commercial_routing_v3.arch_prompts import (
    PROMPT_A1,
    PROMPT_A2,
    PROMPT_B_EXTRACT,
    build_a1_classify_prompt,
    build_a2_category_prompt,
    build_b_extract_prompt,
)
from src.services.commercial_routing_v3.prompt import PROMPT_VERSION as V5
from src.services.commercial_routing_v3.registry_extract_mapper import (
    PROVENANCE,
    RegistryVocab,
    map_extracted_to_categories,
)


def test_production_prompt_untouched() -> None:
    assert V5 == "v3_category_centric_routing_7b_v5"
    assert PROMPT_A1 != V5
    assert PROMPT_A2 != V5


def test_a1_has_no_registry_or_categories() -> None:
    text = build_a1_classify_prompt(title="Поставка моноблока", okpd_code="26.2", okpd_name="ПК")
    assert "Do NOT emit commercial category" in text
    assert "commercial_category_hypotheses" not in text
    assert "procured_items" in text
    assert "explicit_goods" in text
    assert "evidence_phrases" in text


def test_a2_category_only() -> None:
    reg = [{"category_code": "computers", "category_name": "Компьютеры"}]
    text = build_a2_category_prompt(
        title="Поставка моноблока",
        okpd_code="26.2",
        okpd_name="ПК",
        procurement_form="DIRECT_GOODS_PURCHASE",
        procured_items=["моноблок"],
        explicit_goods=["моноблок"],
        registry=reg,
    )
    assert "A2_ONLY_CATEGORY_TASK=YES" in text
    assert "FORCED_OBJECT_CATEGORY=NO" in text
    assert "- computers" in text


def test_b_extract_no_category_choice() -> None:
    text = build_b_extract_prompt(title="Поставка моноблока", okpd_code="26.2", okpd_name="ПК")
    assert "Do NOT choose commercial category" in text
    assert "procured_items" in text


def test_mapper_no_hardcoded_monoblock_impersonation() -> None:
    vocab = RegistryVocab()
    vocab.term_to_codes = {"компьютер": {"computers"}}
    vocab.terms_sorted = ["компьютер"]
    out = map_extracted_to_categories(
        {
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "procured_items": ["моноблок"],
            "is_service": False,
        },
        vocab,
        allowed={"computers"},
    )
    assert out["provenance"] == PROVENANCE
    assert out["EXTRACT_MAP_IMPERSONATES_MODEL"] is False
    assert out["commercial_category_hypotheses"] == []
    assert "моноблок" in (out.get("registry_vocabulary_gaps") or [])


def test_mapper_maps_via_registry_vocab_only() -> None:
    vocab = RegistryVocab()
    vocab.term_to_codes = {"моноблок": {"computers"}}
    vocab.terms_sorted = ["моноблок"]
    out = map_extracted_to_categories(
        {
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "procured_items": ["моноблок"],
            "is_service": False,
        },
        vocab,
        allowed={"computers"},
    )
    assert out["commercial_category_hypotheses"][0]["category_code"] == "computers"
    assert out["commercial_category_hypotheses"][0]["confidence"] is None
