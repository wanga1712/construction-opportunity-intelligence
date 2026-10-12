"""MEDAL SEMANTICS V2 contract tests (ANALYTICS-V2-MEDAL-SEMANTICS-V2-REBUILD-1, PHASE 6.4).

Business invariant under test:

    CATEGORY RELEVANCE            ->  MEDAL
    PRICE / DEADLINE / URGENCY    ->  RANKING
    PRICE MUST NEVER CREATE RELEVANCE.

Every test below locks exactly one acceptance clause of the WIP (§35).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.services.effective_medal_service import (
    resolve_card_effective_medals,
    resolve_model_medal_authority,
)
from src.services.first_pass.resolver import resolve_canonical_preliminary_medal
from src.services.first_pass.service import FirstPassService
from src.services.medal_semantics_v2 import (
    CANONICAL_CATEGORY_CODES,
    MEDAL_SEMANTICS_VERSION,
    PRODUCTION_MODEL,
    PRODUCTION_PROMPT_VERSION,
    evaluate_category,
    is_model_authority_current,
    relevance_level,
    strongest_category_medal,
)
from src.services.second_pass_prompt_v2 import build_second_pass_prompt
from src.services.second_pass_service import parse_second_pass_json
from src.ui.components.analytics_v2.card_trust import resolve_level

# ── Production regression material (§9, §15) ──────────────────────────────────

PRINTER_CARTRIDGES_TITLE = (
    "Поставка элементов замены типовых устройств ввода и вывода "
    "(картриджи для принтеров), блока фотобарабана"
)
ASSISTIVE_DEVICES_TITLE = (
    "Поставка вспомогательных электронных средств ориентации "
    "для социального обеспечения получателей"
)
ROAD_LIGHTING_TITLE = (
    "Выполнение работ по содержанию элементов линий электроосвещения "
    "и светофорных объектов на автодорогах"
)
BASEMENT_REPAIR_TITLE = (
    "Выполнение работ по капитальному ремонту подвального помещения. "
    "Детская школа искусств"
)
COMPUTERS_TITLE = "Поставка ноутбуков, серверов и мониторов"

#: The only weight-80 OKPD prior in production (computers / 26.20 / PREFIX).
COMPUTERS_PRIOR = [{"commercial_category_code": "computers", "prior_weight": 80.0}]

CURRENT_RUN = {
    "inference_run_id": 991,
    "run_kind": "PRODUCTION",
    "run_status": "COMPLETED",
    "prompt_version": PRODUCTION_PROMPT_VERSION,
    "model_name": PRODUCTION_MODEL,
    "semantics_version": MEDAL_SEMANTICS_VERSION,
}


def _proc(pid: int = 1, *, title: str = "", price: float = 1_000_000.0) -> dict:
    return {
        "id": pid,
        "contract_number": f"N-{pid}",
        "auction_name": title,
        "okpd_code": "26.20.40.120",
        "initial_price": price,
        "end_date": "2030-01-01",
    }


def _cat_eval(code: str, level: str, **extra) -> dict:
    payload = {"category_code": code, "relevance_level": level}
    payload.update(extra)
    return payload


def _card_candidate(**overrides) -> dict:
    card = {
        "id": 46550,
        "is_confirmed": False,
        "expert_medal": None,
        "preliminary_medal": "BRONZE",
        "model_medal": "GOLD",
        "end_date": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
    }
    card.update(CURRENT_RUN)
    card.update(overrides)
    return card


# ── §4 BARE_OKPD_GOLD = 0 ─────────────────────────────────────────────────────

def test_bare_okpd_prior_never_produces_a_medal():
    """OKPD may nominate a category; it can never supply medal strength."""
    medal, score, _conf, source, category, *_ = resolve_canonical_preliminary_medal(
        okpd_target_classification="TARGET",
        matched_priors=COMPUTERS_PRIOR,
    )
    assert medal == "UNASSESSED"
    assert score == 0.0
    assert source == "UNASSESSED"
    assert category is None


@pytest.mark.parametrize(
    "title",
    [
        PRINTER_CARTRIDGES_TITLE,      # CRM_ID=46550
        ASSISTIVE_DEVICES_TITLE,       # CRM_ID=215064
        ROAD_LIGHTING_TITLE,           # CRM_ID=216341
        BASEMENT_REPAIR_TITLE,         # CRM_ID=216435
    ],
)
def test_bare_okpd_prior_with_irrelevant_metadata_is_never_gold(title):
    medal, _score, _conf, source, category, *_ = resolve_canonical_preliminary_medal(
        okpd_target_classification="TARGET",
        matched_priors=COMPUTERS_PRIOR,
        title=title,
    )
    assert medal != "GOLD"
    if medal != "UNASSESSED":
        assert category in CANONICAL_CATEGORY_CODES
        assert source == "METADATA_CATEGORY_SEMANTIC"


# ── §5 PRELIM_GOLD_WITHOUT_CANONICAL_CATEGORY = 0 ─────────────────────────────

@pytest.mark.parametrize(
    "title",
    [
        "",
        PRINTER_CARTRIDGES_TITLE,
        ASSISTIVE_DEVICES_TITLE,
        ROAD_LIGHTING_TITLE,
        BASEMENT_REPAIR_TITLE,
        COMPUTERS_TITLE,
        "Установка опор контактной сети",
    ],
)
def test_preliminary_medal_never_exists_without_canonical_category(title):
    medal, _score, _conf, _source, category, *_ = resolve_canonical_preliminary_medal(
        okpd_target_classification="TARGET",
        matched_priors=COMPUTERS_PRIOR,
        title=title,
    )
    assert (medal == "UNASSESSED") == (category is None)
    if medal in ("GOLD", "SILVER", "BRONZE", "WOOD"):
        assert category in CANONICAL_CATEGORY_CODES


# ── §12/§13 POSITIVE_CATEGORY_WITHOUT_EVIDENCE = 0 ────────────────────────────

def test_positive_category_requires_evidence():
    raw = json.dumps({
        "category_evaluations": [
            _cat_eval("waterproofing", "STRONG", positive_signals=["гидроизоляция"]),
        ],
    })
    parsed = parse_second_pass_json(raw)
    assert parsed["model_medal"] == "WOOD"
    assert parsed["category_evaluations"][0]["downgrade_reason"] == "POSITIVE_WITHOUT_EVIDENCE"
    assert parsed["category_evaluations"][0]["evidence_supported"] is False


def test_positive_category_requires_semantic_support():
    raw = json.dumps({
        "category_evaluations": [
            _cat_eval(
                "waterproofing",
                "STRONG",
                evidence_refs=[{"document_name": "Смета.pdf", "matched_term": "работы"}],
            ),
        ],
    })
    parsed = parse_second_pass_json(raw)
    assert parsed["model_medal"] == "WOOD"
    assert parsed["category_evaluations"][0]["downgrade_reason"] == "POSITIVE_WITHOUT_SEMANTIC_SUPPORT"


def test_positive_category_with_evidence_and_support_is_gold():
    corpus = "Наплавляемая битумно-полимерная гидроизоляция 846,3 м2"
    raw = json.dumps({
        "category_evaluations": [
            _cat_eval(
                "waterproofing",
                "STRONG",
                evidence_refs=[{
                    "document_name": "Смета.pdf",
                    "matched_term": "гидроизоляция",
                    "quote": corpus,
                }],
            ),
        ],
    })
    parsed = parse_second_pass_json(raw, corpus)
    assert parsed["model_medal"] == "GOLD"
    assert parsed["category_evaluations"][0]["evidence_supported"] is True


# ── §8 PRICE_AFFECTS_MEDAL = NO ───────────────────────────────────────────────

def test_price_is_structurally_absent_from_second_pass_prompt():
    stats = {"document_count": 3, "processed_document_count": 3, "evidence_count": 12}
    snippets = [{
        "category_code": "computers",
        "document_name": "D.pdf",
        "location": "1:1",
        "matched_term": "ноутбук",
        "text": "ноутбук 3 шт",
    }]
    cheap = build_second_pass_prompt(_proc(1, title="t", price=1_000_000.0), stats, snippets)
    expensive = build_second_pass_prompt(_proc(1, title="t", price=100_000_000.0), stats, snippets)
    assert cheap == expensive
    assert "1000000" not in expensive
    assert "НМЦК:" not in expensive  # price value is never rendered into the prompt


def test_price_cannot_change_category_medal_or_priority():
    """Same metadata/evidence at 1M and 100M -> identical category and medal."""
    cheap = _proc(101, title=COMPUTERS_TITLE, price=1_000_000.0)
    expensive = _proc(102, title=COMPUTERS_TITLE, price=100_000_000.0)
    results = FirstPassService().evaluate_batch([cheap, expensive])
    a, b = results[101], results[102]
    assert a.canonical_preliminary_medal == b.canonical_preliminary_medal == "GOLD"
    assert a.category == b.category == "computers"
    assert a.canonical_preliminary_score == b.canonical_preliminary_score
    assert a.priority_score == b.priority_score


def test_second_pass_marks_price_as_unused_for_medal():
    parsed = parse_second_pass_json("{}")
    assert parsed["price_used_for_medal"] is False
    assert parsed["raw_model_suggestion"]["authoritative"] is False


# ── §16 OVERALL_MODEL_MEDAL = strongest canonical category ────────────────────

def test_overall_model_medal_equals_strongest_canonical_category():
    corpus = "Наплавляемая гидроизоляция кровли; монтаж светильников ДПА"
    raw = json.dumps({
        "category_evaluations": [
            _cat_eval(
                "lighting",
                "MODERATE",
                evidence_refs=[{
                    "document_name": "D.pdf",
                    "matched_term": "светильников",
                    "quote": "монтаж светильников ДПА",
                }],
            ),
            _cat_eval(
                "waterproofing",
                "STRONG",
                evidence_refs=[{
                    "document_name": "D.pdf",
                    "matched_term": "гидроизоляция",
                    "quote": "Наплавляемая гидроизоляция кровли",
                }],
            ),
        ],
    })
    parsed = parse_second_pass_json(raw, corpus)
    assert parsed["model_medal"] == "GOLD"
    by_category = {e["category_code"]: e["relevance_medal"] for e in parsed["category_evaluations"]}
    assert by_category == {"lighting": "SILVER", "waterproofing": "GOLD"}


@pytest.mark.parametrize(
    "levels,expected",
    [
        (["WEAK"], "BRONZE"),
        (["MODERATE", "WEAK"], "SILVER"),
        (["STRONG", "MODERATE"], "GOLD"),
        (["NONE"], "WOOD"),
    ],
)
def test_overall_model_medal_never_exceeds_strongest_category(levels, expected):
    evaluations = [
        {"category_code": "lighting", "relevance_level": lvl, "evidence_supported": True}
        for lvl in levels
    ]
    assert strongest_category_medal(evaluations, require_evidence=True) == expected


def test_strongest_category_medal_ignores_non_canonical_codes():
    evaluations = [
        {"category_code": "other_unmapped", "relevance_level": "STRONG", "evidence_supported": True},
        {"category_code": "lighting", "relevance_level": "WEAK", "evidence_supported": True},
    ]
    assert strongest_category_medal(evaluations, require_evidence=True) == "BRONZE"


def test_strongest_category_medal_returns_none_without_any_category():
    assert strongest_category_medal([]) is None
    assert strongest_category_medal([], require_evidence=True) is None


def test_strongest_category_medal_requires_evidence_when_asked():
    evaluations = [{"category_code": "lighting", "relevance_level": "STRONG", "evidence_supported": False}]
    assert strongest_category_medal(evaluations) == "GOLD"
    assert strongest_category_medal(evaluations, require_evidence=True) is None


# ── §17 no category = WOOD, pending = UNASSESSED ──────────────────────────────

def test_completed_analysis_without_canonical_category_is_wood():
    raw = json.dumps({
        "category_evaluations": [_cat_eval("other_unmapped", "STRONG")],
        "model_reason": "профиль не определён",
    })
    parsed = parse_second_pass_json(raw, "текст документов без профильных сигналов")
    assert parsed["model_medal"] == "WOOD"
    assert parsed["model_state"] == "ASSESSED"


def test_pending_analysis_is_unassessed_not_wood():
    parsed = parse_second_pass_json("{}", "", analysis_ready=False)
    assert parsed["model_medal"] is None
    assert parsed["model_state"] == "UNASSESSED"
    assert parsed["model_score"] == 0


def test_unassessed_card_is_not_presented_as_a_medal():
    card = {
        "processing_stage": "matches_found",
        "preliminary_medal": None,
        "model_medal": None,
        "effective_medal": "UNASSESSED",
    }
    _label, _color, _bg, is_medal = resolve_level(card)
    assert is_medal is False


# ── §2 LEGACY_RUNLESS_MODEL_AUTHORITY = 0 ─────────────────────────────────────

def test_current_semantics_v2_run_is_model_authority():
    card = resolve_card_effective_medals(_card_candidate())
    assert card["model_medal_authority"] == "CURRENT"
    assert card["base_medal"] == "GOLD"
    assert card["base_medal_authority"] == "SECOND_PASS_MODEL"


def test_legacy_run_less_assessment_cannot_be_model_authority():
    card = resolve_card_effective_medals(_card_candidate(inference_run_id=None))
    assert card["model_medal_authority"] == "LEGACY"
    assert card["model_medal"] == "GOLD"          # the row is kept, never deleted
    assert card["base_medal"] == "BRONZE"         # falls back to PRELIMINARY
    assert card["base_medal_authority"] == "PRELIMINARY"


def test_old_prompt_result_cannot_be_current_authority():
    card = resolve_card_effective_medals(
        _card_candidate(prompt_version="v3_second_pass_legacy_7b")
    )
    assert card["model_medal_authority"] == "LEGACY"
    assert card["base_medal_authority"] == "PRELIMINARY"


def test_stale_model_result_is_not_authority():
    card = resolve_card_effective_medals(_card_candidate(is_stale=True))
    assert card["model_medal_authority"] == "LEGACY"


def test_model_medal_authority_is_absent_without_a_model_medal():
    assert resolve_model_medal_authority({"model_medal": None}) == "ABSENT"


@pytest.mark.parametrize(
    "override",
    [
        {"inference_run_id": None},
        {"inference_run_id": 0},
        {"run_kind": "SHADOW"},
        {"run_status": "FAILED"},
        {"prompt_version": "v3_second_pass_legacy_7b"},
        {"model_name": "qwen2.5:3b"},
        {"semantics_version": 1},
        {"semantics_version": None},
        {"is_stale": True},
    ],
)
def test_is_model_authority_current_rejects_non_current_results(override):
    kwargs = dict(CURRENT_RUN)
    kwargs.update(override)
    assert is_model_authority_current(**kwargs) is False


def test_is_model_authority_current_accepts_production_v2_run():
    assert is_model_authority_current(**CURRENT_RUN) is True


# ── §20/§22 SINGLE_UI_MEDAL_AUTHORITY ─────────────────────────────────────────

def test_single_ui_medal_authority_across_all_surfaces():
    """list / detail / dashboard all render the one resolved effective medal."""
    card = resolve_card_effective_medals(_card_candidate())
    assert card["effective_medal"] == "GOLD"
    for stage in ("raw", "documents_loaded", "matches_found", "ai_verified", "ranked", "manager_confirmed"):
        label, _color, _bg, is_medal = resolve_level(dict(card, processing_stage=stage))
        assert is_medal is True, stage
        assert label.startswith("Gold"), stage


def test_legacy_model_never_reaches_the_ui_as_gold():
    card = resolve_card_effective_medals(_card_candidate(inference_run_id=None))
    label, _color, _bg, is_medal = resolve_level(dict(card, processing_stage="matches_found"))
    assert is_medal is True
    assert label.startswith("Bronze")


@pytest.mark.parametrize(
    "days,base,expected",
    [
        (30, "GOLD", "GOLD"),
        (10, "GOLD", "SILVER"),
        (5, "GOLD", "BRONZE"),
        (2.5, "GOLD", "WOOD"),
        (30, "BRONZE", "BRONZE"),
        (30, "WOOD", "WOOD"),
    ],
)
def test_time_decay_never_promotes_a_medal(days, base, expected):
    card = resolve_card_effective_medals({
        "end_date": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(),
        "is_confirmed": False,
        "model_medal": None,
        "preliminary_medal": base,
    })
    assert card["base_medal"] == base
    assert card["effective_medal"] == expected


# ── §14 SEMANTIC GUARDS ───────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "category,text",
    [
        ("lighting", "Установка опор контактной сети"),
        ("flooring", "Обратная засыпка котлована и траншей"),
        ("flooring", "Устройство наливного пола"),
        ("waterproofing", "Нанесение грунтовки по бетону"),
        ("waterproofing", "Изоляция трубопровода"),
        ("waterproofing", "Устройство теплоизоляции кровли"),
    ],
)
def test_ambiguous_terms_do_not_grant_category_relevance(category, text):
    assert evaluate_category(category, text)["relevance_level"] == "NONE"


def test_road_and_construction_regressions_have_no_category_semantics():
    assert evaluate_category("lighting", ROAD_LIGHTING_TITLE)["relevance_level"] == "NONE"
    assert evaluate_category("waterproofing", BASEMENT_REPAIR_TITLE)["relevance_level"] == "NONE"
    assert evaluate_category("flooring", BASEMENT_REPAIR_TITLE)["relevance_level"] == "NONE"


def test_single_metadata_signal_is_only_weak_relevance():
    assert relevance_level(0, 0) == "NONE"
    assert relevance_level(1, 0) == "WEAK"
    assert relevance_level(2, 0) == "MODERATE"
    assert relevance_level(3, 0) == "STRONG"
    # negative context always caps: three positives plus one exclusion is not GOLD
    assert relevance_level(3, 1) == "WEAK"


# ── Version hygiene ───────────────────────────────────────────────────────────

def test_every_second_pass_result_carries_semantics_version_two():
    parsed = parse_second_pass_json("{}")
    assert parsed["semantics_version"] == MEDAL_SEMANTICS_VERSION == 2
    assert parsed["prompt_version"] == PRODUCTION_PROMPT_VERSION
    assert parsed["model_name"] == PRODUCTION_MODEL

# ?? Evidence selector plumbing (module split regression) ??????????????????????

class _FakeCursor:
    def __init__(self, details):
        self._details = details

    def execute(self, sql, params=None):
        self._sql = sql

    def fetchone(self):
        return (5, 5, 7, "application/pdf")

    def fetchall(self):
        return self._details

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, details):
        self._details = details

    def cursor(self):
        return _FakeCursor(self._details)


def test_evidence_selector_maps_category_code_to_canonical_and_reads_existing_rows():
    """``extract_evidence_snippets`` must stay importable from the new module.

    It reads only existing ``document_match_details`` rows (no re-download or
    re-parse) and normalizes the row category onto a canonical code.
    """
    from src.services.second_pass_evidence import extract_evidence_snippets

    detail = (
        1, "26.20", "sub", "????????", 0.9, "p.1:2",
        {"values": {"name": "???????? HP 106A", "qty": 1, "unit": "??"}},
        "tz.pdf",
    )
    snippets, stats = extract_evidence_snippets(_FakeConn([detail]), 46550)
    assert len(snippets) == 1
    assert snippets[0]["category_code"] == "computers"
    assert snippets[0]["document_name"] == "tz.pdf"
    assert snippets[0]["matched_term"] == "????????"
    assert stats["document_count"] == 5

# ── Tokenizer lexeme-separation regressions (§14 semantic guards) ──────────────

def test_tokenizer_keeps_distinct_lexemes_apart():
    """Regression: a shared prefix used to equate different words.

    ``парк``/«паркет» resolved flooring from the word «индустриального парка» and
    ``монитор``/«мониторинг» resolved computers from «экологический мониторинг».
    """
    from src.services.medal_semantics_v2 import _tokens_equal

    assert _tokens_equal("парк", "паркет") is False
    assert _tokens_equal("парка", "паркет") is False
    assert _tokens_equal("монитор", "мониторингу") is False
    assert _tokens_equal("мост", "мостовой") is False
    # genuine inflection is still tolerated
    assert _tokens_equal("светильник", "светильников") is True
    assert _tokens_equal("бетон", "бетонные") is True
    assert _tokens_equal("ограждение", "ограждений") is True


def test_industrial_park_title_is_not_flooring():
    title = (
        "Выполнение работ по завершению строительства «Строительство 3-й очереди "
        "инженерно-транспортной инфраструктуры индустриального парка «Есипово»"
    )
    assert evaluate_category("flooring", title)["relevance_level"] == "NONE"


def test_ecological_monitoring_is_not_computers():
    title = "Оказание услуг по экологическому мониторингу водохранилища Сестрорецкий Разлив"
    assert evaluate_category("computers", title)["relevance_level"] == "NONE"


def test_road_lighting_evidence_still_matches_lighting_category():
    """The real 216341 evidence must survive the stricter tokenizer."""
    evidence = "Ж/б опоры освещения СВ-110-5 шт. 79"
    assert "опора освещения" in evaluate_category("lighting", evidence)["positive_signals"]
