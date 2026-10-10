from pathlib import Path
from typing import Any, Dict, Tuple

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from ..smeta_forma_4b import detect_forma_4b


#: Форма 4б column labels: the flat "a | b | c" dump cannot tell quantity from
#: unit price, which is why the model produced quotes like "1354 1010 шт. шт.".
_FORMA_4B_LABELS = (
    ("C", "Наименование"),
    ("D", "Ед.изм."),
    ("E", "Объём"),
    ("F", "Цена за ед."),
    ("I", "Стоимость базис"),
    ("J", "Индекс"),
    ("K", "Стоимость текущая"),
)


class ExcelParser:
    def parse(self, path: Path) -> str:
        text, _ = self.parse_with_meta(path)
        return text

    @staticmethod
    def _read_workbook(
        path: Path, *, data_only: bool
    ) -> Tuple[str, Dict[int, Dict[str, Any]]]:
        workbook = load_workbook(
            filename=str(path), read_only=True, data_only=data_only
        )
        parts: list[str] = []
        line_meta: Dict[int, Dict[str, Any]] = {}
        line_index = 0
        sheet_titles: list[str] = []
        main_rows: list[Tuple[Any, Dict[str, str]]] = []
        try:
            for sheet_position, sheet in enumerate(workbook.worksheets):
                sheet_name = sheet.title
                sheet_titles.append(sheet_name)
                for row in sheet.iter_rows(values_only=False):
                    cell_items: list[dict] = []
                    cell_texts: list[str] = []
                    row_cells: Dict[str, str] = {}
                    row_index_val = None
                    for cell in row:
                        value = cell.value
                        if value is None:
                            continue
                        text = str(value).strip()
                        if not text:
                            continue
                        text = text.replace("\n", " ").replace("\r", " ")
                        cell_texts.append(text)
                        cell_items.append({
                            "text": text,
                            "column_letter": get_column_letter(cell.column),
                            "cell_address": cell.coordinate,
                        })
                        row_cells[get_column_letter(cell.column)] = text
                        row_index_val = cell.row
                    if not cell_texts:
                        continue
                    parts.append(" | ".join(cell_texts))
                    line_index += 1
                    line_meta[line_index] = {
                        "sheet_name": sheet_name,
                        "row_index": row_index_val,
                        "cells": cell_items,
                    }
                    if sheet_position == 0:
                        main_rows.append((row_index_val, row_cells))
        finally:
            workbook.close()
        if detect_forma_4b(sheet_titles):
            parts.append(
                "СМЕТА ФОРМА 4Б — РАЗМЕЧЕННЫЕ СТРОКИ (Ед.изм., Цена за ед., "
                "Стоимость базис/текущая):"
            )
            line_index += 1
            line_meta[line_index] = {"sheet_name": sheet_titles[0], "row_index": None, "cells": []}
            for row_index_val, cells in main_rows:
                if not cells.get("C") or not cells.get("D"):
                    continue
                # Only material lines carry a unit price / cost; work rows have
                # those columns empty (their costs live in other columns).
                if not (cells.get("F") or cells.get("I")):
                    continue
                line = "СТРОКА %s: %s" % (
                    row_index_val,
                    " | ".join(f"{label}: {cells.get(column, '')}" for column, label in _FORMA_4B_LABELS),
                )
                parts.append(line)
                line_index += 1
                line_meta[line_index] = {
                    "sheet_name": sheet_titles[0],
                    "row_index": row_index_val,
                    "cells": [{"text": line, "column_letter": "", "cell_address": ""}],
                }
        return "\n".join(parts), line_meta

    def parse_with_meta(self, path: Path) -> Tuple[str, Dict[int, Dict[str, Any]]]:
        text, line_meta = self._read_workbook(path, data_only=True)
        if text:
            return text, line_meta
        # Formula-only workbooks often have no cached values. Reopen them with
        # formulas visible instead of incorrectly reporting an empty parse.
        return self._read_workbook(path, data_only=False)
