"""Canonical text normalization for matching, rules and the model prompt.

Pure, dependency-free. Produces:
- ``normalize_text``: lower-case, ё→е, punctuation/spaces canonical;
- ``expand_abbreviations``: ПОДД/ОВ/ИТП/АР/КЖ/УУТЭ/НМЦК/… expansions;
- ``canonical_tokens``: text → normalized tokens with light RU stemming;
- ``match_key``: stable signature used by POSITIVE/NEGATIVE rules and the prompt.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Sequence

_PUNCT = re.compile(r"[^\w\s+№]", re.UNICODE)
_SPACES = re.compile(r"\s+")
_KM_RE = re.compile(r"\bкм\s*0*(\d+)\+(\d+)", re.IGNORECASE)

ABBREVIATIONS = {
    "подд": "проект организации дорожного движения",
    "ов": "отопление вентиляция",
    "итп": "индивидуальный тепловой пункт",
    "уутэ": "узел учета тепловой энергии",
    "кж": "конструкции железобетонные",
    "ар": "архитектурные решения",
    "тз": "техническое задание",
    "смр": "строительно монтажные работы",
    "кипиа": "контрольно измерительные приборы автоматика",
    "нмцк": "начальная максимальная цена контракта",
    "этп": "электронная торговая площадка",
}

_STOPWORDS = frozenset((
    "выполнение", "работ", "работы", "услуг", "оказание", "по", "на", "в", "и", "для",
    "с", "от", "до", "объекту", "объект", "закупка", "поставка", "ремонт", "капитальный",
    "текущий", "строительство", "г", "области", "края", "район", "город", "территории",
))

# Light Russian suffix stripping (no external morphology dependency).
_SUFFIXES = ("иями", "ями", "ами", "ией", "ей", "ой", "ий", "ый", "ая", "яя", "ые",
             "ие", "ов", "ев", "ах", "ях", "ам", "ям", "ов", "ы", "и", "а", "я", "е", "у", "ю")


def normalize_text(value: object) -> str:
    text = str(value or "").lower().replace("ё", "е")
    text = _KM_RE.sub(lambda m: f"км {m.group(1)}+{m.group(2)}", text)
    text = _PUNCT.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def expand_abbreviations(value: object, *, keep_original: bool = True) -> str:
    text = normalize_text(value)
    out: List[str] = []
    for token in text.split():
        expansion = ABBREVIATIONS.get(token)
        if expansion:
            out.append(expansion)
            if keep_original:
                out.append(token)
        else:
            out.append(token)
    return _SPACES.sub(" ", " ".join(out)).strip()


def _stem(token: str) -> str:
    if len(token) <= 4:
        return token
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def canonical_tokens(value: object, *, expand: bool = True, drop_stopwords: bool = True) -> List[str]:
    text = expand_abbreviations(value) if expand else normalize_text(value)
    tokens = []
    for token in text.split():
        if drop_stopwords and token in _STOPWORDS:
            continue
        tokens.append(_stem(token))
    return tokens


def match_key(value: object, *, max_tokens: int = 8) -> str:
    """Stable signature: normalized, expanded, stemmed, order-preserving tokens."""
    tokens = canonical_tokens(value)
    return " ".join(tokens[:max_tokens])


def signature_phrases(value: object, *, sizes: Sequence[int] = (3, 2),
                      max_phrases: int = 3) -> List[str]:
    """Distinctive n-grams (by stemmed tokens) for POSITIVE/NEGATIVE phrase rules."""
    tokens = canonical_tokens(value)
    phrases: List[str] = []
    for n in sizes:
        for i in range(len(tokens) - n + 1):
            phrase = " ".join(tokens[i:i + n])
            if phrase not in phrases:
                phrases.append(phrase)
            if len(phrases) >= max_phrases:
                return phrases
    return phrases or [" ".join(tokens)]
