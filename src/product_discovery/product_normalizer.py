"""Product and material name normalization into canonical category titles."""

from __future__ import annotations

import re
from typing import Optional


# Precompiled regex patterns for standard category extraction
CANONICAL_RULES = [
    (re.compile(r"\bопор[а-я]*\s+(?:металлическ[а-я]*|гранен[а-я]*|коническ[а-я]*|силов[а-я]*|несилов[а-я]*|огк|от|сф|нф|осв[а-я]*)", re.IGNORECASE), "Опора наружного освещения"),
    (re.compile(r"\bопор[а-я]*\s+(?:освещен[а-я]*|наружн[а-я]*\s+освещен[а-я]*)", re.IGNORECASE), "Опора наружного освещения"),
    (re.compile(r"\bсветильник[а-я]*\s+(?:светодиодн[а-я]*|уличн[а-я]*|консольн[а-я]*|дку|жку|led)", re.IGNORECASE), "Светильник уличный светодиодный"),
    (re.compile(r"\bпрожектор[а-я]*\s+(?:светодиодн[а-я]*|led|заливочн[а-я]*)", re.IGNORECASE), "Прожектор светодиодный"),
    (re.compile(r"\bкронштейн[а-я]*\s+(?:для\s+светильник[а-я]*|освещен[а-я]*|к1|к2|к3)", re.IGNORECASE), "Кронштейн освещения"),
    (re.compile(r"\bкабел[а-я]*\s+(?:силов[а-я]*|ввг|вббшв|вбшв|авббшв|аввг)", re.IGNORECASE), "Кабель силовой"),
    (re.compile(r"\bкабел[а-я]*\s+(?:оптическ[а-я]*|волс|оптоволоконн[а-я]*)", re.IGNORECASE), "Кабель оптический"),
    (re.compile(r"\bлифт[а-я]*\s+(?:пассажирск[а-я]*)", re.IGNORECASE), "Лифт пассажирский"),
    (re.compile(r"\bлифт[а-я]*\s+(?:грузов[а-я]*)", re.IGNORECASE), "Лифт грузовой"),
    (re.compile(r"\bшприц[а-я]*\s+(?:одноразов[а-я]*|инъекционн[а-я]*|трехкомпонентн[а-я]*|двухкомпонентн[а-я]*)", re.IGNORECASE), "Шприц медицинский"),
    (re.compile(r"\bтруб[а-я]*\s+(?:стальн[а-я]*|профильн[а-я]*|бесшовн[а-я]*|электросварн[а-я]*)", re.IGNORECASE), "Труба стальная"),
    (re.compile(r"\bтруб[а-я]*\s+(?:полиэтилен[а-я]*|пнд|пэ\s*\d+|гофрированн[а-я]*)", re.IGNORECASE), "Труба полиэтиленовая"),
    (re.compile(r"\bнасос[а-я]*\s+(?:погружн[а-я]*|скважинн[а-я]*|дренажн[а-я]*|центробежн[а-я]*)", re.IGNORECASE), "Насос скважинный"),
    (re.compile(r"\bшкаф[а-я]*\s+(?:управлен[а-я]*|распределительн[а-я]*|вру|щсу|вводно-распределительн[а-я]*)", re.IGNORECASE), "Шкаф управления и распределения"),
]

# Patterns to strip technical noise
RE_NOISE = re.compile(
    r"\b(гост\s*[\d\.\-]+|ту\s*[\d\.\-]+|паспорт|сертификат|г\/п|серия|\d+х\d+(?:х\d+)?|\d+\s*мм|\d+\s*вт|\d+\s*w|\d+\s*v|\d+\s*в|\d+\s*м\/с)\b",
    re.IGNORECASE,
)


def normalize_product_name(raw_name: Optional[str]) -> str:
    """Canonicalizes raw product description into standardized product category title."""
    if not raw_name:
        return "Неизвестный товар"

    text = raw_name.strip()

    # 1. Match standard canonical rule patterns
    for pattern, canonical in CANONICAL_RULES:
        if pattern.search(text):
            return canonical

    # 2. Heuristic fallback: clean codes, brand tokens, and dimensions
    cleaned = RE_NOISE.sub("", text)
    cleaned = re.sub(r"[\"\'«»\(\)\[\],;\:]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    words = cleaned.split()
    if not words:
        return text[:60]

    # Take first 2-3 words as base category name
    base = " ".join(words[:3])
    return base[:60].capitalize()
