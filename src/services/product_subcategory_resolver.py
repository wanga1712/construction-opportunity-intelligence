"""Deterministic product-subcategory resolver (no model, no Qwen).

Given a procurement's commercial category, its title, already-known document
facts and (for computers) structured TZ items, return AT MOST one active
``PRODUCT`` subcategory for that category — or ``NULL``.

Priority (strict):

1. ``COMPUTER_STRUCTURED`` — structured computer TZ items / supplier card.
2. ``DOC_FACT`` — existing ``crm_object_subcategory_links`` fact, same category,
   subcategory must be an active ``PRODUCT`` node.
3. ``TERM_MATCH`` — deterministic phrase match over the union of
   ``crm_product_subcategory_terms`` and the builtin product lexicon below.
4. otherwise ``NULL``.

``OBJECT_CONTEXT`` / ``MIXED_LEGACY`` subcategories are NEVER returned here.
When two candidates tie, the row stays UNCLASSIFIED (no random choice).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

SOURCE_COMPUTER_STRUCTURED = "COMPUTER_STRUCTURED"
SOURCE_DOC_FACT = "DOC_FACT"
SOURCE_TERM_MATCH = "TERM_MATCH"

# The literal sentinel that used to sit in commercial_subcategory_code. It is
# NOT a real subcategory and must be treated exactly like NULL.
UNCLASSIFIED_SENTINEL = "SUBCATEGORY_NOT_ASSIGNED"

# structured computer item category -> product subcategory
COMPUTER_ITEM_CATEGORY_MAP: Dict[str, str] = {
    "notebook": "laptops",
    "laptop": "laptops",
    "desktop": "desktop_computers",
    "monoblock": "all_in_one_computers",
    "all_in_one": "all_in_one_computers",
    "server": "servers",
    "mfu": "printing_equipment",
    "printer": "printing_equipment",
    "mouse": "computer_peripherals",
    "keyboard": "computer_peripherals",
    "peripheral": "computer_peripherals",
    "monitor": "monitors",
    "ups": "ups_power_protection",
    "network": "network_equipment",
    # 'software' / 'other' intentionally resolve to nothing
}

# Deterministic lexicon for product nodes that have no DB terms yet (the new
# lighting/composites nodes) plus a few high-value gap phrases. Keys are
# category_code -> subcategory_code -> positive phrases.
BUILTIN_TERMS: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "computers": {
        "network_equipment": (
            "сетевое оборудование", "сетевого оборудования", "сетевым оборудованием",
            "сетевое оборудован", "сетевое и серверное",
        ),
        "workstation_kits": (
            "автоматизированное рабочее место",
            "автоматизированных рабочих мест",
            "автоматизированные рабочие места",
        ),
    },
    "lighting": {
        "street_luminaires": (
            "уличный светильник", "уличные светильники",
            "дорожный светильник", "дорожные светильники",
            "консольный светильник", "наружный светильник",
        ),
        "lighting_poles": (
            "опора освещения", "опоры освещения", "опору освещения",
            "опора наружного освещения", "опоры наружного освещения",
            "столб освещения", "мачта освещения",
        ),
        "indoor_luminaires": (
            "внутренний светильник", "внутренние светильники",
            "внутреннее освещение",
        ),
        "architectural_lighting": (
            "архитектурное освещение", "архитектурный светильник",
            "фасадное освещение", "фасадный светильник", "подсветка",
        ),
        "lighting_controls": (
            "управление освещением", "аппаратура управления освещением",
            "диммируем", "пускатель", "балласт",
        ),
    },
    "composites": {
        "pultruded_profiles": ("пултруз",),
        "frp_gratings": ("решетчатый настил", "решётчатый настил", "решётк", "решетк"),
        "composite_guardrails": ("перильное ограждение", "перильные ограждения"),
        "composite_cornice_blocks": ("карнизный блок", "карнизные блоки"),
        "composite_pipeline_casings": ("футляр", "футляры трубопровод"),
        "composite_concrete_fiber": ("фибра",),
        "composite_cable_trays": ("кабельный лоток", "кабельные лотки"),
        "polymer_chutes": ("быстроток", "водоотводный лоток", "водоотводные лотки"),
    },
}

_WS = re.compile(r"\s+")

# Computers: a kit must win over its parts. If a "host" signal (desktop /
# system unit / personal computer) co-occurs with a monitor, a peripheral or a
# kit marker ("в комплекте", "комплект "), the primary subcategory is a
# workstation kit — never computer_peripherals / monitors / desktop_computers.
COMPUTER_KIT_PHRASES: Tuple[str, ...] = ("в комплекте", "комплект ")
_COMPUTER_HOST_CODES = ("desktop_computers", "workstation_kits")
_COMPUTER_UNIT_CODES = (
    "desktop_computers", "workstation_kits", "laptops",
    "all_in_one_computers", "servers",
)


@dataclass(frozen=True)
class Resolution:
    subcategory_code: Optional[str]
    confidence: float
    source: Optional[str]
    reason: str = ""


@dataclass
class ResolverInput:
    category_code: str
    title: str = ""
    tz_text: str = ""
    doc_facts: Sequence[Tuple[str, str]] = field(default_factory=tuple)
    computer_categories: Sequence[str] = field(default_factory=tuple)
    # Title/term matching is only trustworthy for product-supply procurements;
    # for construction works the title describes the object, not the product.
    allow_term_match: bool = True


@dataclass
class ResolverContext:
    """Preloaded reference data; keeps resolve() pure and testable."""

    # category_code -> set of active PRODUCT subcategory codes
    product_by_category: Dict[str, set] = field(default_factory=dict)
    # category_code -> subcategory_code -> term_type -> [(phrase, weight)]
    terms_by_category: Dict[str, Dict[str, Dict[str, List[Tuple[str, float]]]]] = field(
        default_factory=dict
    )
    computer_item_map: Dict[str, str] = field(
        default_factory=lambda: dict(COMPUTER_ITEM_CATEGORY_MAP)
    )
    builtin_terms: Dict[str, Dict[str, Tuple[str, ...]]] = field(
        default_factory=lambda: {k: dict(v) for k, v in BUILTIN_TERMS.items()}
    )


def _norm(value: Optional[str]) -> str:
    if not value:
        return ""
    return _WS.sub(" ", value.lower().replace("ё", "е")).strip()


def _matches(text: str, phrase: str) -> bool:
    p = _norm(phrase)
    if not p:
        return False
    if len(p) < 4:
        pattern = r"(?<![a-zа-я0-9])" + re.escape(p) + r"(?![a-zа-я0-9])"
        return re.search(pattern, text) is not None
    return p in text


def _unique(codes: Sequence[Optional[str]]) -> List[str]:
    seen: List[str] = []
    for code in codes:
        if code and code not in seen:
            seen.append(code)
    return seen


def is_unclassified(code: Optional[str]) -> bool:
    """True for NULL / empty / the legacy literal sentinel."""
    if code is None:
        return True
    value = str(code).strip()
    return value == "" or value == UNCLASSIFIED_SENTINEL


def _resolve_computer_structured(
    inp: ResolverInput, ctx: ResolverContext
) -> Optional[Resolution]:
    product = ctx.product_by_category.get(inp.category_code, set())
    mapped = _unique(
        [ctx.computer_item_map.get(_norm(c).strip()) for c in inp.computer_categories]
    )
    mapped = [c for c in mapped if c in product]
    if len(mapped) == 1:
        return Resolution(mapped[0], 0.95, SOURCE_COMPUTER_STRUCTURED, "structured item")
    if len(mapped) > 1:
        return Resolution(None, 0.0, None, "ambiguous_structured")
    return None


def _resolve_doc_fact(inp: ResolverInput, ctx: ResolverContext) -> Optional[Resolution]:
    product = ctx.product_by_category.get(inp.category_code, set())
    codes = _unique(
        [code for (cat, code) in inp.doc_facts if cat == inp.category_code]
    )
    codes = [c for c in codes if c in product]
    if len(codes) == 1:
        return Resolution(codes[0], 0.90, SOURCE_DOC_FACT, "document fact")
    if len(codes) > 1:
        return Resolution(None, 0.0, None, "ambiguous_doc_fact")
    return None


def _resolve_term_match(inp: ResolverInput, ctx: ResolverContext) -> Resolution:
    product = ctx.product_by_category.get(inp.category_code, set())
    if not product:
        return Resolution(None, 0.0, None, "no_product_taxonomy")
    text = _norm(f"{inp.title} {inp.tz_text}")
    if not text:
        return Resolution(None, 0.0, None, "empty_text")

    cat_terms = ctx.terms_by_category.get(inp.category_code, {})
    builtin = ctx.builtin_terms.get(inp.category_code, {})

    scores: Dict[str, float] = {}
    hits: Dict[str, int] = {}
    for code in product:
        score = 0.0
        count = 0
        for phrase, weight in cat_terms.get(code, {}).get("search", []):
            if _matches(text, phrase):
                score += weight or 100
                count += 1
        for phrase in builtin.get(code, ()):
            if _matches(text, phrase):
                score += 100
                count += 1
        for phrase, weight in cat_terms.get(code, {}).get("negative", []):
            if _matches(text, phrase):
                score -= weight or 100
        if score > 0:
            scores[code] = score
            hits[code] = count

    if not scores:
        return Resolution(None, 0.0, None, "no_match")

    if inp.category_code == "computers":
        override, scores = _computer_precedence(text, scores)
        if override and override in product:
            return Resolution(override, 0.75, SOURCE_TERM_MATCH,
                              "computer_kit_precedence")
        hits = {c: h for c, h in hits.items() if c in scores}
        if not scores:
            return Resolution(None, 0.0, None, "no_match")

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    best_code, best_score = ranked[0]
    if len(ranked) > 1 and ranked[1][1] >= best_score:
        return Resolution(None, 0.0, None, "ambiguous_term")
    confidence = round(min(0.95, 0.60 + 0.05 * max(0, hits[best_code] - 1)), 4)
    return Resolution(best_code, confidence, SOURCE_TERM_MATCH, "term match")


def _computer_precedence(
    text: str, scores: Dict[str, float]
) -> Tuple[Optional[str], Dict[str, float]]:
    """Apply the computer kit/peripheral precedence to matched subcategories."""
    host = any(code in scores for code in _COMPUTER_HOST_CODES)
    monitor = "monitors" in scores
    peripheral = "computer_peripherals" in scores
    kit_marker = any(_matches(text, phrase) for phrase in COMPUTER_KIT_PHRASES)

    if host and (monitor or peripheral or kit_marker):
        return "workstation_kits", scores

    # peripherals must never pull a whole unit/kit
    if peripheral and any(code in scores for code in _COMPUTER_UNIT_CODES):
        filtered = {c: v for c, v in scores.items() if c != "computer_peripherals"}
        return None, filtered
    return None, scores


def resolve(inp: ResolverInput, ctx: ResolverContext) -> Resolution:
    """Deterministic resolution; never returns OBJECT_CONTEXT / MIXED_LEGACY."""
    if inp.category_code not in ctx.product_by_category:
        return Resolution(None, 0.0, None, "unknown_category")

    if inp.category_code == "computers" and inp.computer_categories:
        result = _resolve_computer_structured(inp, ctx)
        if result is not None:
            return result

    if inp.doc_facts:
        result = _resolve_doc_fact(inp, ctx)
        if result is not None:
            return result

    if not inp.allow_term_match:
        return Resolution(None, 0.0, None, "non_product_track")

    return _resolve_term_match(inp, ctx)
