"""Составное правило для композитных водоотводных лотков.

Обычный список фраз не ловит формулировки вроде:
«Лотки линейного водоотвода, изготовленные из полимерного композитного материала».

Правило требует совместного присутствия:
изделие + назначение + материал
и отбрасывает кабельные/теплотрассные/связные лотки.
"""
from __future__ import annotations

import re
from typing import Any


CANONICAL_NAME = "Композитный водоотводный лоток"

PRODUCT_TERMS = (
    "лоток",
    "лотки",
    "канал",
    "каналы",
    "система водоотвода",
)

PURPOSE_TERMS = (
    "водоотвод",
    "водоотводный",
    "водоотводные",
    "дренаж",
    "дренажный",
    "дренажные",
    "ливневый",
    "ливневые",
    "линейный водоотвод",
)

MATERIAL_TERMS = (
    "композит",
    "композитный",
    "композитные",
    "композитного материала",
    "полимерный композит",
    "полимеркомпозитный",
    "полимеркомпозитные",
    "стеклопластик",
    "стеклопластиковый",
    "стеклопластиковые",
)

STOP_CONTEXT_TERMS = (
    "кабель",
    "кабельный",
    "кабельные",
    "кабеленесущ",
    "лоток связи",
    "связь",
    "связной",
    "теплотрасс",
    "инженерные коммуникации",
    "электромонтаж",
    "электромонтажный",
)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[а-яёa-z0-9]+", text.lower())


def _term_present(text: str, term: str) -> bool:
    term = term.lower()
    if "*" in term:
        return term.replace("*", "") in text
    return term in text


def _first_pos(tokens: list[str], variants: tuple[str, ...]) -> int | None:
    joined = " ".join(tokens)
    best: int | None = None
    for term in variants:
        term_tokens = _tokens(term)
        if not term_tokens:
            continue
        if len(term_tokens) == 1:
            needle = term_tokens[0]
            for idx, token in enumerate(tokens):
                if token.startswith(needle[: max(5, min(len(needle), 8))]) or needle in token:
                    best = idx if best is None else min(best, idx)
                    break
            continue
        phrase = " ".join(term_tokens)
        if phrase in joined:
            idx = joined[: joined.index(phrase)].count(" ")
            best = idx if best is None else min(best, idx)
    return best


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_term_present(text, term) for term in terms)


def match_composite_drainage(
    lines: list[str],
    *,
    line_meta: dict[int, dict[str, Any]] | None = None,
    max_distance_words: int = 15,
) -> list[dict[str, Any]]:
    """Ищет составное совпадение по строкам.

    Для таблиц текущий парсер уже отдаёт строку целиком/ячейки как line, поэтому
    правило работает по строке. Соседние строки не подтверждают совпадение
    автоматически — это сделано намеренно, чтобы не ловить ложняк.
    """
    matches: list[dict[str, Any]] = []
    meta = line_meta or {}

    for idx, original_line in enumerate(lines):
        text = original_line.lower()
        if not text.strip():
            continue
        if _has_any(text, STOP_CONTEXT_TERMS):
            continue
        if not (_has_any(text, PRODUCT_TERMS) and _has_any(text, PURPOSE_TERMS) and _has_any(text, MATERIAL_TERMS)):
            continue

        tokens = _tokens(text)
        product_pos = _first_pos(tokens, PRODUCT_TERMS)
        purpose_pos = _first_pos(tokens, PURPOSE_TERMS)
        material_pos = _first_pos(tokens, MATERIAL_TERMS)
        if product_pos is None or purpose_pos is None or material_pos is None:
            continue
        if max(product_pos, purpose_pos, material_pos) - min(product_pos, purpose_pos, material_pos) > max_distance_words:
            continue

        line_number = idx + 1
        item: dict[str, Any] = {
            "keyword": CANONICAL_NAME,
            "score": 100,
            "level": "green",
            "line_number": line_number,
            "matched_line": original_line,
            "matched_display_text": original_line,
            "match_rule": "composite_drainage_compound",
            "product_group": "composites",
        }
        if line_number in meta:
            item.update(meta[line_number])
        matches.append(item)

    return matches
