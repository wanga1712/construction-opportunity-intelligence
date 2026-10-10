"""V3 canonical text normalization + normalized prompt signal block."""
from __future__ import annotations

from src.services.commercial_routing_v3.prompt_signals import normalized_signal_block
from src.services.commercial_routing_v3.text_normalization import (
    canonical_tokens,
    expand_abbreviations,
    match_key,
    normalize_text,
    signature_phrases,
)


def test_normalize_text_lowercases_drops_punctuation_and_maps_lyo() -> None:
    assert normalize_text("  Ёлка, ОВ;  ПОДД! ") == "елка ов подд"
    assert normalize_text("№ 5 (АР)") == "№ 5 ар"
    assert normalize_text("км 012+300") == "км 12+300"
    assert normalize_text(None) == ""


def test_expand_abbreviations_keeps_original_by_default() -> None:
    out = expand_abbreviations("ПОДД")
    assert "проект организации дорожного движения" in out
    assert "подд" in out
    assert (
        expand_abbreviations("ПОДД", keep_original=False)
        == "проект организации дорожного движения"
    )


def test_canonical_tokens_drop_stopwords_and_stem() -> None:
    assert canonical_tokens("Поставка светильников уличных") == ["светильник", "уличных"]


def test_match_key_is_stable_and_order_preserving() -> None:
    assert match_key("Поставка светильников уличных") == "светильник уличных"
    assert match_key("") == ""


def test_signature_phrases_prefers_trigrams() -> None:
    phrases = signature_phrases("Поставка светильников уличных с монтажом")
    assert phrases
    assert all(isinstance(p, str) and p for p in phrases)


def test_normalized_signal_block_matches_inflected_phrases() -> None:
    signals = [
        {"commercial_category_code": "lighting", "signal_type": "POSITIVE_SIGNAL",
         "phrase": "светильник"},
        {"commercial_category_code": "lighting", "signal_type": "NEGATIVE_SIGNAL",
         "phrase": "отопление"},
    ]
    block = normalized_signal_block({"title": "Поставка светильников с отоплением"}, signals)
    assert "NORMALIZED_INPUT_SIGNALS" in block
    assert "match_key: светильник отоплением" in block
    assert "[в заголовке: светильник]" in block
    assert "мы видим здесь категорию lighting" in block
    assert "[в заголовке: отопление]" in block  # stem-prefix catches "отоплением"
    assert "категорию lighting не предлагать" in block


def test_normalized_signal_block_is_empty_without_title_or_signals() -> None:
    assert normalized_signal_block({"title": ""}, []) == ""
