"""Normalization: ё, punctuation, abbreviations, stemming, signatures."""
from src.services.commercial_routing_v3.text_normalization import (
    canonical_tokens,
    expand_abbreviations,
    match_key,
    normalize_text,
    signature_phrases,
)


def test_normalize_text_basics():
    assert normalize_text("Отсыпка ЩЕБНЁМ, ул. Шипово!") == "отсыпка щебнем ул шипово"
    assert normalize_text("км 004+150") == "км 4+150"


def test_abbreviation_expansion():
    assert "проект организации дорожного движения" in expand_abbreviations("ПОДД")
    assert "индивидуальный тепловой пункт" in expand_abbreviations("ПНР ИТП, УУТЭ")


def test_tokens_stem_and_drop_stopwords():
    tokens = canonical_tokens("Выполнение работ по отсыпке щебнем")
    assert "выполнени" not in tokens and "работ" not in tokens
    assert any(t.startswith("отсып") for t in tokens)


def test_match_key_equivalence():
    a = match_key("Отсыпка щебнем участков дороги")
    b = match_key("отсыпка щебёнкой участка дороги")
    assert a.split()[0] == b.split()[0]  # same stemmed head token
    assert "щебн" in a


def test_signature_phrases():
    phrases = signature_phrases("Выполнение работ по отсыпке щебнем участков дороги")
    assert phrases and any("щебн" in p for p in phrases)
