"""Сборка текстовых строк и метаданных ячеек из табличных данных."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


_MULTI_SPACE = re.compile(r"\s{2,}")


def dedupe_merged_cells(cells: List[str]) -> List[str]:
    """Убирает дубли подряд — типичный артефакт объединённых ячеек Word."""
    result: List[str] = []
    for cell in cells:
        value = (cell or "").strip()
        if not value:
            continue
        if result and result[-1] == value:
            continue
        result.append(value)
    return result


def split_ocr_line_to_cells(line: str) -> List[str]:
    """Разбивает OCR-строку на ячейки по табам или группам пробелов."""
    raw = (line or "").strip()
    if not raw:
        return []
    if "\t" in raw:
        parts = [p.strip() for p in raw.split("\t")]
    else:
        parts = [p.strip() for p in _MULTI_SPACE.split(raw)]
    return [p for p in parts if p]


def append_table_row(
    parts: List[str],
    line_meta: Dict[int, Dict[str, Any]],
    cell_texts: List[str],
    *,
    page_number: Optional[int] = None,
    table_index: Optional[int] = None,
    row_index: Optional[int] = None,
    sheet_name: Optional[str] = None,
) -> None:
    """Добавляет одну строку таблицы в общий текст и line_meta."""
    cleaned = [c.replace("\n", " ").replace("\r", " ").strip() for c in cell_texts if c and str(c).strip()]
    if not cleaned:
        return

    row_text = " | ".join(cleaned)
    parts.append(row_text)
    line_number = len(parts)

    cell_items: List[dict] = []
    for idx, text in enumerate(cleaned, start=1):
        cell_items.append({
            "text": text,
            "column_letter": _column_letter(idx),
            "cell_address": f"col{idx}",
        })

    meta: Dict[str, Any] = {
        "cells": cell_items,
        "row_index": row_index,
        "table_index": table_index,
    }
    if page_number is not None:
        meta["page_number"] = page_number
    if sheet_name:
        meta["sheet_name"] = sheet_name
    line_meta[line_number] = meta


def append_plain_line(
    parts: List[str],
    line_meta: Dict[int, Dict[str, Any]],
    text: str,
    *,
    page_number: Optional[int] = None,
) -> None:
    """Добавляет обычную текстовую строку (не таблица)."""
    # Переносы в абзацах ломают нумерацию line_meta при text.splitlines()
    value = (text or "").replace("\r", " ").replace("\n", " ")
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return
    parts.append(value)
    line_number = len(parts)
    if page_number is not None:
        line_meta[line_number] = {"page_number": page_number}


def append_ocr_table_lines(
    parts: List[str],
    line_meta: Dict[int, Dict[str, Any]],
    page_text: str,
    *,
    page_number: int,
    min_columns: int = 3,
) -> None:
    """Из OCR-текста страницы выделяет строки, похожие на таблицу."""
    for raw_line in page_text.splitlines():
        cells = split_ocr_line_to_cells(raw_line)
        if len(cells) >= min_columns:
            append_table_row(
                parts,
                line_meta,
                cells,
                page_number=page_number,
                table_index=0,
            )
        elif raw_line.strip():
            append_plain_line(parts, line_meta, raw_line, page_number=page_number)


def _column_letter(index: int) -> str:
    """1 → A, 2 → B, ... (упрощённо для CRM)."""
    letters = ""
    n = index
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters or "A"
