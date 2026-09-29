"""MEDAL SEMANTICS V2 — commercial medal = canonical-category relevance.

Business invariant (ANALYTICS-V2-MEDAL-SEMANTICS-V2-REBUILD-1):

    CATEGORY RELEVANCE  ->  MEDAL
    PRICE / DEADLINE / URGENCY  ->  RANKING

Hard rules enforced here:
  * price never creates relevance (it is absent from every function below);
  * a medal above UNASSESSED requires a canonical commercial category;
  * a bare OKPD prior never produces a medal (OKPD may only nominate a
    candidate category, never supply medal strength);
  * the overall model medal is the strongest supported canonical category
    medal — deterministic, never a free-form model verdict;
  * positive category medals require evidence.

The canonical category registry (crm_product_categories) is a frozen
authority: it is mirrored read-only here, not redefined.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

MEDAL_SEMANTICS_VERSION = 2
MEDAL_SEMANTICS_TAG = "medal_semantics_v2"

#: Prompt/model that may act as current model authority.
PRODUCTION_MODEL = "qwen2.5:7b"
PRODUCTION_PROMPT_VERSION = "v4_second_pass_category_semantics_7b_v1"

MEDAL_SEQUENCE: Tuple[str, ...] = ("GOLD", "SILVER", "BRONZE", "WOOD")
MEDAL_RANK: Dict[str, int] = {"GOLD": 4, "SILVER": 3, "BRONZE": 2, "WOOD": 1, "UNASSESSED": 0}

RELEVANCE_LEVELS: Tuple[str, ...] = ("STRONG", "MODERATE", "WEAK", "NONE")

#: Deterministic relevance -> medal mapping (applied by code, never by Qwen).
RELEVANCE_TO_MEDAL: Dict[str, str] = {
    "STRONG": "GOLD",
    "MODERATE": "SILVER",
    "WEAK": "BRONZE",
    "NONE": "WOOD",
}
MEDAL_TO_RELEVANCE: Dict[str, str] = {v: k for k, v in RELEVANCE_TO_MEDAL.items()}

#: Minimum evidence references required for a positive category medal.
POSITIVE_MEDALS: Tuple[str, ...] = ("GOLD", "SILVER", "BRONZE")

CANONICAL_CATEGORY_CODES: Tuple[str, ...] = (
    "lighting",
    "waterproofing",
    "flooring",
    "composites",
    "computers",
    "drainage_water_management",
    "structural_reinforcement",
    "composite_structures",
    "bridge_road_infrastructure",
    "external_utility_networks",
    "concrete_materials",
    "cable_support_systems",
    "waterproofing_concrete_repair",
    "curbstone",
)


class _Signals:
    """Positive / negative / ambiguous vocabulary for one canonical category."""

    __slots__ = ("positive", "negative", "ambiguous")

    def __init__(
        self,
        positive: Sequence[str],
        negative: Sequence[str] = (),
        ambiguous: Sequence[str] = (),
    ) -> None:
        self.positive = tuple(positive)
        self.negative = tuple(negative)
        self.ambiguous = tuple(ambiguous)


# Mirror of crm_product_categories.positive_signals / negative_contexts, plus the
# regression guards demanded by the WIP (ambiguous general terms must not carry a
# category on their own).  No new taxonomy is introduced: every entry belongs to
# an existing canonical category.
CATEGORY_SIGNALS: Dict[str, _Signals] = {
    "lighting": _Signals(
        positive=(
            "светильник", "прожектор", "опора освещения", "наружное освещение",
            "аварийное освещение", "уличное освещение", "уличный фонарь",
            "светодиодный", "лампа", "лампы", "ДРЛ", "ДНаТ", "освещение",
        ),
        negative=("электромонтаж без поставки светильников",),
        ambiguous=("опора", "светофор", "подсветка", "электромонтаж"),
    ),
    "waterproofing": _Signals(
        positive=(
            "гидроизоляция", "гидроизоляционный материал", "рулонная изоляция",
            "битумная мастика", "проникающая гидроизоляция", "гидроизоляционная мембрана",
            "мастика битумная", "наплавляемая", "мембрана профилированная",
        ),
        negative=("теплоизоляция", "минераловатные", "минеральная вата", "изоляция трубопровода"),
        ambiguous=("изоляция", "грунтовка", "грунтовочный", "обмазка"),
    ),
    "flooring": _Signals(
        positive=(
            "тротуарная плитка", "резиновая плитка", "брусчатка", "напольное покрытие",
            "искусственная трава", "резиновое покрытие", "спортивное покрытие",
            "линолеум", "керамогранит", "ламинат", "паркет",
        ),
        negative=(
            "обратная засыпка", "засыпка котлована", "засыпка траншей", "земляные работы",
        ),
        ambiguous=("полы", "наливной", "покрытие", "засыпка", "котлован", "грунт"),
    ),
    "computers": _Signals(
        positive=(
            "компьютер", "ноутбук", "системный блок", "сервер", "монитор", "МФУ",
            "принтер", "планшет", "АРМ", "рабочая станция", "вычислительная техника",
        ),
        negative=(
            "программное обеспечение без поставки оборудования",
            "техническое обслуживание без поставки",
        ),
        ambiguous=("картридж", "фотобарабан", "тонер", "периферия", "заправка"),
    ),
    "cable_support_systems": _Signals(
        positive=(
            "кабельный лоток", "кабельный короб", "кабеленесущая система",
            "кабеленесущий", "лоток металлический", "проволочный лоток",
        ),
        negative=("кабель", "провод", "светильник"),
        ambiguous=("лоток", "короб"),
    ),
    "concrete_materials": _Signals(
        positive=("товарный бетон", "бетонная смесь", "бетон", "цемент", "щебень", "песок", "сухая смесь"),
        negative=("ремонтный состав", "инъекционный состав"),
        ambiguous=("раствор", "смесь"),
    ),
    "composites": _Signals(
        positive=(
            "композитная арматура", "стеклопластиковая арматура", "базальтовая арматура",
            "стеклопластик", "базальтопластик", "углепластик", "FRP", "композитный материал",
        ),
        negative=("металлическая арматура", "стальная арматура"),
        ambiguous=("композит", "арматура"),
    ),
    "composite_structures": _Signals(
        positive=(
            "решётчатый настил", "стеклопластиковая решётка", "composite grating",
            "FRP grating", "ограждение стеклопластик", "перила из ПК", "стеклопластиковый настил",
        ),
        negative=("металлический настил", "стальная решётка"),
        ambiguous=("настил", "решётка", "ограждение"),
    ),
    "structural_reinforcement": _Signals(
        positive=(
            "усиление конструкций", "усиление балок", "усиление перекрытий",
            "углеродная лента", "CFRP", "усиление моста", "анкер",
        ),
        negative=("новое строительство без усиления",),
        ambiguous=("усиление", "лента"),
    ),
    "bridge_road_infrastructure": _Signals(
        positive=(
            "опорная часть моста", "деформационный шов", "перильное ограждение",
            "барьерное ограждение", "дорожное ограждение", "мостовое сооружение",
        ),
        negative=("бордюрный камень", "тротуарная плитка"),
        ambiguous=("мост", "дорога", "ограждение"),
    ),
    "external_utility_networks": _Signals(
        positive=("наружные сети", "трубопровод", "смотровой колодец", "теплоизоляция труб"),
        negative=("внутренние системы здания",),
        ambiguous=("колодец", "сеть"),
    ),
    "curbstone": _Signals(
        positive=("бордюр", "бортовой камень", "лотковый камень", "поребрик", "БР", "БРШ", "БВ"),
        negative=("облицовочный камень без дорожного применения", "декоративный камень фасадный"),
        ambiguous=("камень",),
    ),
    "waterproofing_concrete_repair": _Signals(
        positive=(
            "ремонтный состав", "инъекционный состав", "восстановление бетона",
            "ремонт трещин", "инъектирование трещин", "защитное покрытие бетона", "торкрет",
        ),
        negative=("рулонная гидроизоляция", "кровельная изоляция"),
        ambiguous=("ремонт", "трещина"),
    ),
    "drainage_water_management": _Signals(
        positive=(
            "лоток водоотводный", "водоотводный лоток", "дождеприемник", "пескоуловитель",
            "дренажная труба", "ливневая канализация", "водостоки", "дренаж",
        ),
        negative=("напорная канализация", "ливневая сеть без поставки"),
        ambiguous=("лоток", "канализация", "водоотведение"),
    ),
}

# ── Token matching (Russian-tolerant, deterministic) ──────────────────────────

_TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+")


def _norm_token(token: str) -> str:
    return token.lower().replace("ё", "е")


@lru_cache(maxsize=131072)
def _tokenize_tuple(text: str) -> Tuple[str, ...]:
    return tuple(_norm_token(t) for t in _TOKEN_RE.findall(text))


def tokenize(text: Optional[str]) -> List[str]:
    """Normalize free text into comparable tokens (no stemming library needed).

    Tokenization is pure and the same registry phrases are matched against every
    procurement, so the result is memoized (a fresh list is still returned).
    """
    return list(_tokenize_tuple(text or ""))


#: Russian inflectional endings stripped by the crude stemmer below. Longest
#: first, so that e.g. ``-ными`` wins over ``-ыми``.
_INFLECTION_SUFFIXES: Tuple[str, ...] = (
    "ыми", "ими", "ого", "его", "ому", "ему", "ами", "ями",
    "ная", "ное", "ные", "ный", "ных", "ным", "ной",
    "ая", "яя", "ое", "ее", "ые", "ие", "ый", "ий", "ой", "ей",
    "ов", "ев", "ах", "ях", "ам", "ям", "ом", "ем", "их", "ых",
    "а", "е", "и", "ы", "о", "у", "й", "ь", "я", "ю",
)


@lru_cache(maxsize=131072)
def _stem(token: str) -> str:
    """Strip one inflectional ending, never reducing a token below four letters.

    Pure function of the token; memoized because it is the hottest operation in
    the workset evaluation (millions of calls per stage render).
    """
    for suffix in _INFLECTION_SUFFIXES:
        if len(token) - len(suffix) >= 4 and token.endswith(suffix):
            return token[: len(token) - len(suffix)]
    return token


def _tokens_equal(a: str, b: str) -> bool:
    """Equality of one word root, tolerating Russian inflection only.

    Matching on a shared prefix alone (the earlier rule) conflated distinct
    lexemes: ``парк``/``паркет`` resolved *flooring* from «индустриального
    парка» and ``монитор``/``мониторинг`` resolved *computers* from
    «экологического мониторинга».  Comparing inflectional stems keeps those
    apart while ``светильник``/``светильников`` and ``бетон``/``бетонные`` still match.
    """
    if a == b:
        return True
    return _stem(a) == _stem(b)


def _contains_phrase(haystack: Sequence[str], needle: Sequence[str]) -> bool:
    """Contiguous token-subsequence match."""
    if not needle or len(needle) > len(haystack):
        return False
    for i in range(len(haystack) - len(needle) + 1):
        if all(_tokens_equal(haystack[i + j], needle[j]) for j in range(len(needle))):
            return True
    return False


def _dedupe_overlapping(matched: Sequence[str]) -> List[str]:
    """Drop a matched signal that is fully contained in a longer matched signal."""
    ordered = sorted(matched, key=len, reverse=True)
    kept: List[str] = []
    for sig in ordered:
        sig_tokens = tokenize(sig)
        if any(_contains_phrase(tokenize(k), sig_tokens) for k in kept):
            continue
        kept.append(sig)
    return kept


def match_signals(signals: Iterable[str], text_tokens: Sequence[str]) -> List[str]:
    """Return signals whose phrase is present in the tokenized text."""
    hits = [s for s in signals if _contains_phrase(text_tokens, tokenize(s))]
    return _dedupe_overlapping(hits)


# ── Category semantics ────────────────────────────────────────────────────────

def canonical_category(code: Optional[str]) -> Optional[str]:
    c = (code or "").strip().lower()
    return c if c in CANONICAL_CATEGORY_CODES else None


def relevance_level(positive_hits: int, negative_hits: int) -> str:
    """Deterministic metadata-stage relevance from matched signal counts.

    Negative context always dominates; a single positive signal is never more
    than WEAK (BRONZE) at metadata stage.
    """
    if positive_hits <= 0:
        return "NONE"
    if negative_hits > 0:
        return "WEAK"
    if positive_hits >= 3:
        return "STRONG"
    if positive_hits == 2:
        return "MODERATE"
    return "WEAK"


def evaluate_category(category_code: str, text: Optional[str]) -> Dict[str, Any]:
    """Evaluate one canonical category against free metadata text."""
    cat = canonical_category(category_code)
    if cat is None:
        return {
            "category_code": category_code,
            "relevance_level": "NONE",
            "positive_signals": [],
            "negative_signals": [],
            "ambiguous_signals": [],
        }
    sig = CATEGORY_SIGNALS[cat]
    tokens = tokenize(text)
    pos = match_signals(sig.positive, tokens)
    neg = match_signals(sig.negative, tokens)
    amb = match_signals(sig.ambiguous, tokens)
    return {
        "category_code": cat,
        "relevance_level": relevance_level(len(pos), len(neg)),
        "positive_signals": pos,
        "negative_signals": neg,
        "ambiguous_signals": amb,
    }


def evaluate_metadata_categories(
    text: Optional[str],
    *,
    candidate_categories: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Evaluate canonical categories against metadata text.

    When ``candidate_categories`` is provided (OKPD prior / routing nomination)
    only those categories are scored — OKPD nominates, it never scores.
    """
    codes = list(candidate_categories) if candidate_categories else list(CANONICAL_CATEGORY_CODES)
    out: List[Dict[str, Any]] = []
    seen = set()
    for code in codes:
        cat = canonical_category(code)
        if not cat or cat in seen:
            continue
        seen.add(cat)
        ev = evaluate_category(cat, text)
        if ev["positive_signals"] or ev["negative_signals"]:
            out.append(ev)
    out.sort(key=lambda e: (-MEDAL_RANK.get(RELEVANCE_TO_MEDAL[e["relevance_level"]], 0), e["category_code"]))
    return out


# ── Medal mapping ─────────────────────────────────────────────────────────────

def relevance_to_medal(level: Optional[str]) -> Optional[str]:
    return RELEVANCE_TO_MEDAL.get((level or "").upper())


def medal_to_relevance(medal: Optional[str]) -> str:
    return MEDAL_TO_RELEVANCE.get((medal or "").upper(), "NONE")


def strongest_category_medal(
    evaluations: Sequence[Dict[str, Any]],
    *,
    require_evidence: bool = False,
) -> Optional[str]:
    """Overall medal = strongest supported canonical category medal.

    Returns ``None`` when no canonical category carries a relevance verdict
    (=> UNASSESSED / pending), so callers never mistake "not analysed yet"
    for WOOD.
    """
    best_rank = 0
    best: Optional[str] = None
    for ev in evaluations or []:
        if not isinstance(ev, dict):
            continue
        if canonical_category(ev.get("category_code")) is None:
            continue
        medal = relevance_to_medal(ev.get("relevance_level"))
        if not medal:
            continue
        if require_evidence and medal in POSITIVE_MEDALS and not ev.get("evidence_supported"):
            continue
        rank = MEDAL_RANK.get(medal, 0)
        if rank > best_rank:
            best_rank, best = rank, medal
    return best


def has_canonical_category(evaluations: Sequence[Dict[str, Any]]) -> bool:
    return any(canonical_category((e or {}).get("category_code")) for e in (evaluations or []))


# ── Model authority gate ──────────────────────────────────────────────────────

def is_model_authority_current(
    *,
    inference_run_id: Any,
    run_kind: Optional[str],
    run_status: Optional[str],
    prompt_version: Optional[str],
    model_name: Optional[str],
    semantics_version: Any,
    is_stale: Any = False,
) -> bool:
    """A MODEL result is current authority only if all of this holds.

    Legacy (run-less), stale, other-prompt or non-v2-semantics results keep
    their rows in the DB but are not business authority.
    """
    if inference_run_id in (None, "", 0):
        return False
    if str(run_kind or "").upper() != "PRODUCTION":
        return False
    if str(run_status or "").upper() not in ("COMPLETED", "VALIDATED_SUCCESS"):
        return False
    if str(prompt_version or "") != PRODUCTION_PROMPT_VERSION:
        return False
    if str(model_name or "") != PRODUCTION_MODEL:
        return False
    try:
        if int(semantics_version) != MEDAL_SEMANTICS_VERSION:
            return False
    except (TypeError, ValueError):
        return False
    if bool(is_stale):
        return False
    return True

def record_is_current_model(record: Mapping[str, Any]) -> bool:
    """Reader-level gate for one assessment / model-result record.

    Rows that carry no run, prompt or semantics metadata at all keep the
    historical behaviour (``inference_run_id`` presence), so minimal
    projections and pure unit inputs are unaffected.  As soon as such
    metadata is present the strict MEDAL SEMANTICS V2 test applies: the row
    counts as current authority only when it has a run, is not stale, and
    carries the production prompt and semantics version.  Values that are
    simply absent are assumed current; values that are present and wrong are
    not.
    """
    return is_model_authority_current(
        inference_run_id=record.get("inference_run_id"),
        run_kind=record.get("run_kind") or "PRODUCTION",
        run_status=record.get("run_status") or "COMPLETED",
        prompt_version=record.get("prompt_version") or PRODUCTION_PROMPT_VERSION,
        model_name=record.get("model_name") or PRODUCTION_MODEL,
        semantics_version=record.get(
            "medal_semantics_version",
            record.get("semantics_version", MEDAL_SEMANTICS_VERSION),
        ),
        is_stale=record.get("is_stale"),
    )
