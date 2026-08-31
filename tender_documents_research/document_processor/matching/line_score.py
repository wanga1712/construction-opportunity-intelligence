"""Оценка одной строки текста относительно ключевого слова."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from rapidfuzz import fuzz


@dataclass
class TableLineMatch:
    """Результат оценки строки таблицы."""

    score: int
    winning_cell: Optional[dict] = None
    match_method: str = "UNKNOWN"


def score_table_line(
    keyword: str,
    line_lower: str,
    *,
    required_score: int,
    use_strict_match: bool,
    normalize_line: Callable[[str], str],
    cells: Optional[list[dict]] = None,
) -> Optional[TableLineMatch]:
    """
    Возвращает score строки или None, если совпадения нет.
    При наличии cells проверяет каждую ячейку отдельно — так короткий
    бренд не теряется в длинной строке, а многословный keyword
    не «склеивается» из разных колонок одной строки.
    """
    kw_words = keyword.split()
    kw_len = len(keyword)
    cell_items = cells or []

    if cell_items:
        best: Optional[TableLineMatch] = None
        for cell in cell_items:
            text = str(cell.get("text", "")).lower().strip()
            if not text:
                continue
            match = _score_single_text(
                keyword,
                text,
                kw_words=kw_words,
                kw_len=kw_len,
                required_score=required_score,
                use_strict_match=use_strict_match,
                normalize_line=normalize_line,
            )
            if match is None:
                continue
            if best is None or match.score > best.score:
                best = TableLineMatch(score=match.score, winning_cell=cell, match_method=match.match_method)
        return best

    match = _score_single_text(
        keyword,
        line_lower,
        kw_words=kw_words,
        kw_len=kw_len,
        required_score=required_score,
        use_strict_match=use_strict_match,
        normalize_line=normalize_line,
    )
    if match is None:
        return None
    return TableLineMatch(score=match.score, match_method=match.match_method)


def _score_single_text(
    keyword: str,
    text_lower: str,
    *,
    kw_words: list[str],
    kw_len: int,
    required_score: int,
    use_strict_match: bool,
    normalize_line: Callable[[str], str],
) -> Optional[TableLineMatch]:
    if use_strict_match:
        pattern = (
            r"(^|\s|[^a-zA-Z0-9а-яА-Я])"
            + re.escape(keyword)
            + r"($|\s|[^a-zA-Z0-9а-яА-Я])"
        )
        if re.search(pattern, text_lower):
            return TableLineMatch(score=100, match_method="EXACT")
        return None

    if len(text_lower) < max(3, int(kw_len * 0.3)):
        return None

    if len(text_lower) < kw_len * 1.5:
        score = int(fuzz.ratio(keyword, text_lower))
        method = "FUZZY_RATIO"
    elif kw_len < len(text_lower):
        score = int(fuzz.partial_ratio(keyword, text_lower))
        method = "FUZZY_TOKEN_SET"
    else:
        score = int(fuzz.token_set_ratio(keyword, text_lower))
        method = "FUZZY_TOKEN_SET"

    if score >= required_score:
        if len(kw_words) >= 2 and not _word_coverage_ok(kw_words, text_lower, normalize_line):
            return None
        if not numbers_match(keyword, text_lower):
            return None
        return TableLineMatch(score=score, match_method=method)

    if score >= 50 and len(kw_words) >= 2:
        if _word_coverage_ok(kw_words, text_lower, normalize_line) and numbers_match(keyword, text_lower):
            return TableLineMatch(score=required_score, match_method="STEM_PREFIX")
    return None


def _word_coverage_ok(
    kw_words: list[str],
    matched_line_lower: str,
    normalize_line: Callable[[str], str],
) -> bool:
    """Проверка покрытия значимых слов keyword в строке."""
    meaningful_words = [
        w for w in kw_words if len(w) >= 2 and any(ch.isalpha() for ch in w)
    ]
    if not meaningful_words:
        meaningful_words = [w for w in kw_words if len(w) >= 3 and not w.isdigit()]

    words_present = 0
    for w in meaningful_words:
        if w in matched_line_lower:
            words_present += 1
            continue
        stem_len = max(4, int(len(w) * 0.7))
        stem = w[:stem_len]
        if stem in matched_line_lower:
            words_present += 1
            continue
        w_norm = normalize_line(w)
        if w_norm != w and w_norm in matched_line_lower:
            words_present += 1

    if not meaningful_words:
        return False
    return (words_present / len(meaningful_words)) >= 0.8


def numbers_match(keyword: str, line_lower: str) -> bool:
    """Все числовые токены keyword должны присутствовать в строке."""
    kw_numbers = [w for w in keyword.split() if w.isdigit()]
    if not kw_numbers:
        return True
    for num in kw_numbers:
        pattern = r"(?:^|\b)" + re.escape(num) + r"(?:\b|$)"
        if not re.search(pattern, line_lower):
            return False
    return True


def pick_best_cell(
    keyword: str,
    cells: list[dict],
    *,
    use_strict_match: bool,
) -> tuple[Optional[dict], int]:
    """Выбирает ячейку с лучшим совпадением keyword."""
    kw_len = len(keyword)
    best_cell: Optional[dict] = None
    best_score = -1

    if use_strict_match:
        strict_pattern = (
            r"(^|\s|[^a-zA-Z0-9а-яА-Я])"
            + re.escape(keyword)
            + r"($|\s|[^a-zA-Z0-9а-яА-Я])"
        )
        for cell in cells:
            text = str(cell.get("text", "")).lower()
            if text and re.search(strict_pattern, text):
                return cell, 100

    for cell in cells:
        text = str(cell.get("text", "")).lower().strip()
        if not text or len(text) < kw_len * 0.6:
            continue
        if len(text) < kw_len * 1.5:
            score = int(fuzz.ratio(keyword, text))
        else:
            score = int(fuzz.partial_ratio(keyword, text))
        if score > best_score:
            best_score = score
            best_cell = cell

    if best_cell is None:
        return None, -1
    return best_cell, best_score
