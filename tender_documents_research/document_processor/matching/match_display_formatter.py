"""Форматирование совпадений для CRM (matched_display_text)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Русские подписи полей сметы
FIELD_LABELS: Dict[str, str] = {
    "position": "№",
    "name": "Наименование",
    "unit": "Ед. изм.",
    "qty": "Кол-во",
    "price": "Цена",
    "sum": "Сумма",
    "code": "Шифр/код",
    "content": "Содержание",
}

_LINE_MAX = 140


def _trim(line: str, limit: int = _LINE_MAX) -> str:
    text = " ".join((line or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _format_context_block(title: str, rows: List[str], line_numbers: Optional[List[int]] = None) -> List[str]:
    if not rows:
        return []
    out = [title]
    for i, row in enumerate(rows):
        prefix = f"  {line_numbers[i]}: " if line_numbers and i < len(line_numbers) else "  • "
        out.append(prefix + _trim(row))
    return out


def format_table_values(values: Dict[str, Any]) -> List[str]:
    """Строки «поле: значение» для распознанных колонок сметы."""
    lines: List[str] = []
    for key in ("position", "name", "code", "content", "unit", "qty", "price", "sum"):
        val = values.get(key)
        if val:
            lines.append(f"  {FIELD_LABELS[key]}: {_trim(str(val), 200)}")
    return lines


def format_raw_cells(raw_cells: List[Dict[str, str]]) -> List[str]:
    """Все ячейки строки с подписью колонки из шапки."""
    lines: List[str] = []
    for cell in raw_cells:
        header = (cell.get("header") or "").strip()
        text = (cell.get("text") or "").strip()
        if not text:
            continue
        col = cell.get("col") or "?"
        if header:
            lines.append(f"  {header}: {_trim(text, 200)}")
        else:
            lines.append(f"  [{col}] {_trim(text, 200)}")
    return lines


def format_match_display(
    *,
    keyword: str,
    row_data: Dict[str, Any],
    matched_line: str = "",
    line_number: Optional[int] = None,
    sheet_name: Optional[str] = None,
    page_number: Optional[int] = None,
) -> str:
    """
    Итоговый текст для CRM.
    Структура: шапка → строка таблицы → контекст выше/ниже.
    """
    sections: List[str] = []
    loc_parts: List[str] = []
    if sheet_name:
        loc_parts.append(f"лист {sheet_name}")
    if page_number:
        loc_parts.append(f"стр. {page_number}")
    if line_number and line_number > 0:
        loc_parts.append(f"строка {line_number}")
    header_line = f"▸ {keyword}" + (f" ({', '.join(loc_parts)})" if loc_parts else "")

    values = row_data.get("values") or {}
    raw_cells = row_data.get("raw_cells") or []
    ctx_before: List[str] = row_data.get("context_before") or []
    ctx_after: List[str] = row_data.get("context_after") or []

    sections.append(header_line)

    # Строка таблицы
    field_lines = format_table_values(values)
    if field_lines:
        sections.append("Строка:")
        sections.extend(field_lines)
    elif raw_cells:
        sections.append("Ячейки строки:")
        sections.extend(format_raw_cells(raw_cells))
    elif values.get("text"):
        sections.append(f"Фрагмент: {_trim(str(values['text']), 250)}")
    elif matched_line:
        sections.append(f"Фрагмент: {_trim(matched_line, 250)}")

    # Контекст
    n = row_data.get("context_lines") or len(ctx_before)
    if ctx_before:
        sections.extend(_format_context_block(f"Выше ({min(n, len(ctx_before))} строк):", ctx_before))
    if ctx_after:
        sections.extend(_format_context_block(f"Ниже ({min(n, len(ctx_after))} строк):", ctx_after))

    return "\n".join(sections)


def format_match_summary(values: Dict[str, Any], raw_cells: List[Dict[str, str]], fallback: str = "") -> str:
    """Короткая однострочная выжимка для matched_text."""
    parts: List[str] = []
    for key in ("name", "unit", "qty", "price", "sum"):
        val = values.get(key)
        if val:
            parts.append(str(val).strip())
    if parts:
        return " · ".join(_trim(p, 80) for p in parts)
    if raw_cells:
        texts = [c.get("text", "").strip() for c in raw_cells if c.get("text")]
        if texts:
            return _trim(" | ".join(texts), 200)
    return _trim(fallback, 200)
