"""Оценка совпадения keyword в одной ячейке таблицы."""

from __future__ import annotations

from typing import Callable, Optional

from document_processor.matching.line_score import (
    numbers_match,
    pick_best_cell,
    score_table_line,
)


def score_table_row_cells(
    keyword: str,
    cells: list[dict],
    *,
    required_score: int,
    use_strict_match: bool,
    normalize_line: Callable[[str], str],
) -> tuple[Optional[dict], Optional[int]]:
    """
    Ищет лучшую ячейку строки для keyword.
    Возвращает (cell, score) или (None, None).
    """
    best_cell: Optional[dict] = None
    best_score: Optional[int] = None

    for cell in cells:
        raw = str(cell.get("text", "")).strip()
        if not raw:
            continue
        cell_lower = normalize_line(raw.lower())
        score = score_table_line(
            keyword,
            cell_lower,
            required_score=required_score,
            use_strict_match=use_strict_match,
            normalize_line=normalize_line,
        )
        if score is None:
            continue
        if not use_strict_match and not numbers_match(keyword, cell_lower):
            continue
        if best_score is None or score > best_score:
            best_score = score
            best_cell = cell

    if best_cell is not None:
        return best_cell, best_score

    # Fallback: fuzzy по ячейкам как раньше, если строка не прошла порог поштучно
    picked, picked_score = pick_best_cell(
        keyword,
        cells,
        use_strict_match=use_strict_match,
    )
    if picked is None or picked_score < required_score:
        return None, None
    return picked, picked_score
