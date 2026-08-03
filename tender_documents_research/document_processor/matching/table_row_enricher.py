"""Обогащение совпадений: row_data, заголовки таблиц, контекст ±N строк."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Set, Tuple

from document_processor.matching.match_display_formatter import (
    format_match_display,
    format_match_summary,
)
from document_processor.matching.table_header_detector import build_row_values, detect_header_row


def _context_line_count() -> int:
    try:
        return max(0, int(os.getenv("MATCH_CONTEXT_LINES", "7")))
    except ValueError:
        return 7


class TableRowEnricher:
    """Добавляет row_data и контекст к результатам matcher."""

    def __init__(self, context_lines: Optional[int] = None) -> None:
        self.context_lines = context_lines if context_lines is not None else _context_line_count()
        self._header_cache: Dict[str, Tuple[int, List[dict], Dict[str, int]]] = {}

    def enrich(
        self,
        matches: List[Dict[str, Any]],
        lines: List[str],
        meta: Dict[int, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not matches:
            return matches
        table_groups = self._group_table_lines(meta)
        for match in matches:
            self._enrich_one(match, lines, meta, table_groups)
        return matches

    def _table_key(self, info: Dict[str, Any]) -> str:
        sheet = str(info.get("sheet_name") or "")
        table_index = info.get("table_index")
        page = info.get("page_number")
        return f"{sheet}|{table_index}|{page}"

    def _group_table_lines(
        self, meta: Dict[int, Dict[str, Any]]
    ) -> Dict[str, List[Tuple[int, List[dict]]]]:
        groups: Dict[str, List[Tuple[int, List[dict]]]] = {}
        for line_number, info in sorted(meta.items()):
            if not isinstance(info, dict):
                continue
            cells = info.get("cells")
            if not isinstance(cells, list) or not cells:
                continue
            key = self._table_key(info)
            groups.setdefault(key, []).append((int(line_number), cells))
        return groups

    def _get_header(self, key: str, rows: List[Tuple[int, List[dict]]]) -> Tuple[int, List[dict], Dict[str, int]]:
        if key not in self._header_cache:
            detected = detect_header_row(rows)
            if detected is None:
                self._header_cache[key] = (0, [], {})
            else:
                self._header_cache[key] = detected
        return self._header_cache[key]

    def _lines_in_table(
        self,
        line_number: int,
        meta: Dict[int, Dict[str, Any]],
        table_groups: Dict[str, List[Tuple[int, List[dict]]]],
    ) -> Set[int]:
        info = meta.get(line_number, {})
        key = self._table_key(info) if isinstance(info, dict) else ""
        if key and key in table_groups:
            return {ln for ln, _ in table_groups[key]}
        return {line_number}

    def _collect_context(
        self,
        line_number: int,
        lines: List[str],
        allowed: Set[int],
    ) -> Tuple[List[str], List[str]]:
        n = self.context_lines
        before: List[str] = []
        after: List[str] = []
        for ln in range(line_number - 1, max(0, line_number - n - 1), -1):
            if ln not in allowed:
                break
            idx = ln - 1
            if 0 <= idx < len(lines) and lines[idx].strip():
                before.insert(0, lines[idx].strip())
        for ln in range(line_number + 1, min(len(lines) + 1, line_number + n + 1)):
            if ln not in allowed:
                break
            idx = ln - 1
            if 0 <= idx < len(lines) and lines[idx].strip():
                after.append(lines[idx].strip())
        return before, after

    def _enrich_one(
        self,
        match: Dict[str, Any],
        lines: List[str],
        meta: Dict[int, Dict[str, Any]],
        table_groups: Dict[str, List[Tuple[int, List[dict]]]],
    ) -> None:
        line_number = int(match.get("line_number") or -1)
        if line_number < 1:
            return

        info = meta.get(line_number, {})
        if not isinstance(info, dict):
            info = {}
        cells = info.get("cells")
        allowed = self._lines_in_table(line_number, meta, table_groups)
        context_before, context_after = self._collect_context(line_number, lines, allowed)

        row_data: Dict[str, Any] = {
            "context_before": context_before,
            "context_after": context_after,
            "context_lines": self.context_lines,
        }

        page_number = info.get("page_number")
        sheet_name = match.get("sheet_name") or info.get("sheet_name")

        if isinstance(cells, list) and cells:
            key = self._table_key(info)
            rows = table_groups.get(key, [(line_number, cells)])
            header_ln, header_cells, column_map = self._get_header(key, rows)
            values = build_row_values(cells, column_map, header_cells)
            raw_cells = values.pop("_raw_cells", [])
            if match.get("matched_cell_text"):
                values["_winning_text"] = match.get("matched_cell_text")
            row_data.update({
                "headers": {f: header_cells[i].get("text") for f, i in column_map.items()
                              if header_cells and i < len(header_cells)},
                "values": {k: v for k, v in values.items() if not k.startswith("_")},
                "raw_cells": raw_cells,
                "header_line_number": header_ln,
                "column_map": column_map,
            })
            match["row_data"] = row_data
            match["matched_display_text"] = format_match_display(
                keyword=str(match.get("keyword", "")),
                row_data=row_data,
                matched_line=str(match.get("matched_line") or ""),
                line_number=line_number,
                sheet_name=sheet_name,
                page_number=page_number,
            )
            match["matched_summary"] = format_match_summary(
                row_data.get("values") or {},
                raw_cells,
                str(match.get("matched_cell_text") or match.get("matched_line") or ""),
            )
            return

        idx = line_number - 1
        plain = lines[idx].strip() if 0 <= idx < len(lines) else match.get("matched_line", "")
        row_data["values"] = {"text": plain}
        match["row_data"] = row_data
        match["matched_display_text"] = format_match_display(
            keyword=str(match.get("keyword", "")),
            row_data=row_data,
            matched_line=plain,
            line_number=line_number,
            sheet_name=sheet_name,
            page_number=page_number,
        )
        match["matched_summary"] = format_match_summary({}, [], plain)
