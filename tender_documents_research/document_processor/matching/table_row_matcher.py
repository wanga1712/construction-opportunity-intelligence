"""Поиск совпадений по всем строкам таблиц (не только лучшей)."""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Set

from document_processor.matching.line_score import score_table_line


class TableRowMatcher:
    """
    Для документов с таблицами находит keyword во всех строках смет/спецификаций,
    а не только в одной «лучшей» строке.
    """

    def __init__(self) -> None:
        pass

    def table_line_numbers(self, meta: Dict[int, Dict[str, Any]]) -> Set[int]:
        """Номера строк, относящихся к табличным данным."""
        result: Set[int] = set()
        for line_number, info in meta.items():
            if isinstance(info, dict) and info.get("table_index") is not None:
                result.add(int(line_number))
        return result

    def match_keyword(
        self,
        keyword: str,
        *,
        lines: List[str],
        lines_lower: List[str],
        meta: Dict[int, Dict[str, Any]],
        min_score: int,
        custom_thresholds: Dict[str, int],
        normalize_line: Callable[[str], str],
        is_blocked_by_stop_phrase: Callable[[str, str], bool],
        text_lower: str,
        bm_strict_pattern: re.Pattern[str],
    ) -> List[Dict[str, Any]]:
        """Все совпадения keyword в строках таблиц."""
        table_lines = self.table_line_numbers(meta)
        if not table_lines:
            return []

        is_bm_keyword = bool(bm_strict_pattern.match(keyword))
        use_strict_match = is_bm_keyword or len(keyword) <= 5
        required_score = custom_thresholds.get(keyword, min_score)

        if not use_strict_match and is_blocked_by_stop_phrase(keyword, text_lower):
            return []

        results: List[Dict[str, Any]] = []
        for line_number in sorted(table_lines):
            idx = line_number - 1
            if idx < 0 or idx >= len(lines_lower):
                continue

            extra = meta.get(line_number, {})
            cells = extra.get("cells") if isinstance(extra.get("cells"), list) else []
            line_match = score_table_line(
                keyword,
                lines_lower[idx],
                required_score=required_score,
                use_strict_match=use_strict_match,
                normalize_line=normalize_line,
                cells=cells,
            )
            if line_match is None:
                continue

            matched_line = lines[idx]
            level = "green" if line_match.score >= 95 else "yellow"
            item: Dict[str, Any] = {
                "keyword": keyword,
                "score": line_match.score,
                "level": level,
                "line_number": line_number,
                "matched_line": matched_line,
            }

            for key, value in extra.items():
                item[key] = value

            winning_cell = line_match.winning_cell
            if winning_cell:
                item["matched_cell_text"] = winning_cell.get("text")
                if winning_cell.get("column_letter"):
                    item["column_letter"] = winning_cell.get("column_letter")
                if winning_cell.get("cell_address"):
                    item["cell_address"] = winning_cell.get("cell_address")

            results.append(item)

        return results
