"""Product and material name normalization into canonical category titles across multi-domain taxonomies."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

from src.product_discovery.dto import ProductNormalizationDecision, RowType
from src.product_discovery.row_classifier import classify_row


# Precompiled regex patterns for standard category extraction and domain mapping
CANONICAL_DOMAIN_RULES: List[Tuple[re.Pattern, str, str, str, str, RowType]] = [
    # (Pattern, Canonical Name, Domain, Category, Subcategory, ItemType)
    (re.compile(r"\bопор[а-я]*\s+(?:металлическ[а-я]*|гранен[а-я]*|коническ[а-я]*|силов[а-я]*|несилов[а-я]*|огк|от|сф|нф|осв[а-я]*)", re.IGNORECASE), "Опора наружного освещения", "ELECTRICAL", "Светотехника и опоры", "Опоры освещения", RowType.PRODUCT),
    (re.compile(r"\bопор[а-я]*\s+(?:освещен[а-я]*|наружн[а-я]*\s+освещен[а-я]*)", re.IGNORECASE), "Опора наружного освещения", "ELECTRICAL", "Светотехника и опоры", "Опоры освещения", RowType.PRODUCT),
    (re.compile(r"\bсветильник[а-я]*\s+(?:светодиодн[а-я]*|уличн[а-я]*|консольн[а-я]*|дку|жку|led)", re.IGNORECASE), "Светильник уличный светодиодный", "ELECTRICAL", "Светотехника и опоры", "Светильники уличные", RowType.PRODUCT),
    (re.compile(r"\bпрожектор[а-я]*\s+(?:светодиодн[а-я]*|led|заливочн[а-я]*)", re.IGNORECASE), "Прожектор светодиодный", "ELECTRICAL", "Светотехника и опоры", "Прожекторы", RowType.PRODUCT),
    (re.compile(r"\bкронштейн[а-я]*\s+(?:для\s+светильник[а-я]*|освещен[а-я]*|к1|к2|к3)", re.IGNORECASE), "Кронштейн освещения", "ELECTRICAL", "Светотехника и опоры", "Кронштейны", RowType.PRODUCT),
    (re.compile(r"\bкабел[а-я]*\s+(?:силов[а-я]*|ввг|вббшв|вбшв|авббшв|аввг)", re.IGNORECASE), "Кабель силовой", "ELECTRICAL", "Кабельная продукция", "Кабели силовые", RowType.MATERIAL),
    (re.compile(r"\bкабел[а-я]*\s+(?:оптическ[а-я]*|волс|оптоволоконн[а-я]*)", re.IGNORECASE), "Кабель оптический", "IT", "Сетевое оборудование", "Кабели оптические", RowType.MATERIAL),
    (re.compile(r"\bлифт[а-я]*\s+(?:пассажирск[а-я]*)", re.IGNORECASE), "Лифт пассажирский", "BUILDING_EQUIPMENT", "Лифтовое оборудование", "Лифты пассажирские", RowType.EQUIPMENT),
    (re.compile(r"\bлифт[а-я]*\s+(?:грузов[а-я]*)", re.IGNORECASE), "Лифт грузовой", "BUILDING_EQUIPMENT", "Лифтовое оборудование", "Лифты грузовые", RowType.EQUIPMENT),
    (re.compile(r"\bшприц[а-я]*\s+(?:одноразов[а-я]*|инъекционн[а-я]*|трехкомпонентн[а-я]*|двухкомпонентн[а-я]*)", re.IGNORECASE), "Шприц медицинский", "MEDICAL", "Медицинские расходные материалы", "Шприцы", RowType.PRODUCT),
    (re.compile(r"\bтруб[а-я]*\s+(?:стальн[а-я]*|профильн[а-я]*|бесшовн[а-я]*|электросварн[а-я]*)", re.IGNORECASE), "Труба стальная", "CONSTRUCTION", "Металлопрокат и трубы", "Трубы стальные", RowType.MATERIAL),
    (re.compile(r"\bтруб[а-я]*\s+(?:полиэтилен[а-я]*|пнд|пэ\s*\d+|гофрированн[а-я]*)", re.IGNORECASE), "Труба полиэтиленовая", "CONSTRUCTION", "Трубопроводы и полимеры", "Трубы полиэтиленовые", RowType.MATERIAL),
    (re.compile(r"\bнасос[а-я]*\s+(?:погружн[а-я]*|скважинн[а-я]*|дренажн[а-я]*|центробежн[а-я]*)", re.IGNORECASE), "Насос скважинный", "BUILDING_EQUIPMENT", "Насосное оборудование", "Насосы", RowType.EQUIPMENT),
    (re.compile(r"\bшкаф[а-я]*\s+(?:управлен[а-я]*|распределительн[а-я]*|вру|щсу|вводно-распределительн[а-я]*)", re.IGNORECASE), "Шкаф управления и распределения", "ELECTRICAL", "Низковольтное оборудование", "Шкафы ВРУ/ЩСУ", RowType.EQUIPMENT),
    (re.compile(r"\bсервер[а-я]*\s+(?:стоечн[а-я]*|2u|1u|rack)", re.IGNORECASE), "Сервер стоечный", "IT", "Серверное оборудование", "Серверы", RowType.EQUIPMENT),
    (re.compile(r"\bкоммутатор[а-я]*\s+(?:управляем[а-я]*|l2|l3|poe|switch)", re.IGNORECASE), "Коммутатор сетевой", "IT", "Сетевое оборудование", "Коммутаторы", RowType.EQUIPMENT),
]

# Patterns to strip technical noise
RE_NOISE = re.compile(
    r"\b(гост\s*[\d\.\-]+|ту\s*[\d\.\-]+|паспорт|сертификат|г\/п|серия|\d+х\d+(?:х\d+)?|\d+\s*мм|\d+\s*вт|\d+\s*w|\d+\s*v|\d+\s*в|\d+\s*м\/с)\b",
    re.IGNORECASE,
)


def normalize_product_name(raw_name: Optional[str]) -> str:
    """Canonicalizes raw product description into standardized product category title (legacy/fast helper)."""
    if not raw_name:
        return "Неизвестный товар"

    text = raw_name.strip()
    for pattern, canonical, _, _, _, _ in CANONICAL_DOMAIN_RULES:
        if pattern.search(text):
            return canonical

    cleaned = RE_NOISE.sub("", text)
    cleaned = re.sub(r"[\"\'«»\(\)\[\],;\:]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    words = cleaned.split()
    if not words:
        return text[:60]
    base = " ".join(words[:3])
    return base[:60].capitalize()


class RuleBasedProductNormalizerV1:
    """High-precision rule-based normalizer mapping text to multi-domain taxonomy decisions."""

    def normalize(
        self,
        raw_text: str,
        okpd_code: str = "",
        section_name: str = "",
        unit_raw: str = "",
        total_amount: float = 0.0,
    ) -> ProductNormalizationDecision:
        """Determines item type, canonical title, and domain taxonomy classification."""
        clean_text = (raw_text or "").strip()
        classified_type = classify_row(clean_text, unit_raw, total_amount)

        for pattern, canonical, domain, category, subcategory, item_type in CANONICAL_DOMAIN_RULES:
            if pattern.search(clean_text):
                return ProductNormalizationDecision(
                    item_type=item_type if classified_type in (RowType.PRODUCT, RowType.MATERIAL, RowType.EQUIPMENT, RowType.UNKNOWN) else classified_type,
                    normalized_product_name=canonical,
                    domain=domain,
                    category_name=category,
                    subcategory_name=subcategory,
                    product_family=canonical,
                    aliases=[clean_text] if clean_text != canonical else [],
                    confidence=0.92,
                    novelty_probability=0.05,
                    explanation=f"Matched canonical rule for {canonical} in domain {domain}",
                )

        # Domain fallback by OKPD prefix
        domain = "CONSTRUCTION"
        okpd_pfx = okpd_code.split(".")[0] if okpd_code else ""
        if okpd_pfx in ("26", "62", "63"):
            domain = "IT"
        elif okpd_pfx in ("27",):
            domain = "ELECTRICAL"
        elif okpd_pfx in ("28",):
            domain = "BUILDING_EQUIPMENT"
        elif okpd_pfx in ("21", "32"):
            domain = "MEDICAL"
        elif okpd_pfx in ("31",):
            domain = "FURNITURE"

        norm_name = normalize_product_name(clean_text)
        return ProductNormalizationDecision(
            item_type=classified_type,
            normalized_product_name=norm_name,
            domain=domain,
            category_name=f"{domain.title()} товары",
            subcategory_name=norm_name,
            product_family=norm_name,
            aliases=[clean_text] if clean_text != norm_name else [],
            confidence=0.70,
            novelty_probability=0.35,
            explanation=f"Heuristic normalization into domain {domain}",
        )


class ModelProductNormalizerV1:
    """Standardized product normalizer with in-memory caching and rule-based fallback."""

    def __init__(self, fallback_normalizer: Optional[RuleBasedProductNormalizerV1] = None) -> None:
        self.fallback = fallback_normalizer or RuleBasedProductNormalizerV1()
        self._cache: Dict[str, ProductNormalizationDecision] = {}

    def _cache_key(self, raw_text: str, okpd_code: str, section_name: str) -> str:
        sig = f"{raw_text.strip()}:{okpd_code.strip()}:{section_name.strip()}".encode("utf-8")
        return hashlib.sha256(sig).hexdigest()

    def normalize(
        self,
        raw_text: str,
        okpd_code: str = "",
        section_name: str = "",
        procurement_title: str = "",
        unit_raw: str = "",
        total_amount: float = 0.0,
    ) -> ProductNormalizationDecision:
        """Normalizes candidate item with caching and structured decision output."""
        ckey = self._cache_key(raw_text, okpd_code, section_name)
        if ckey in self._cache:
            return self._cache[ckey]

        decision = self.fallback.normalize(
            raw_text=raw_text,
            okpd_code=okpd_code,
            section_name=section_name,
            unit_raw=unit_raw,
            total_amount=total_amount,
        )
        self._cache[ckey] = decision
        return decision

