"""Определение строки заголовков таблицы и маппинг колонок смет/спецификаций."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Стандартные поля → подстроки в заголовках (нижний регистр)
HEADER_FIELD_SYNONYMS: Dict[str, Tuple[str, ...]] = {
    "position": ("№", "п/п", "поз", "номер поз", "n п/п"),
    "name": (
        "наименование",
        "наимен",
        "работ",
        "материал",
        "описание",
        "конструктив",
        "вид работ",
    ),
    "unit": ("ед.изм", "ед. изм", "единица", "ед ", "изм", "ед."),
    "qty": ("кол-во", "количество", "кол ", "объём", "объем", "масса"),
    "price": ("цена за ед", "цена/ед", "расценка", "цена ", "стоимость ед"),
    "sum": ("сумма", "стоимость", "всего", "итого"),
    "code": ("шифр", "обоснование", "код", "индекс"),
}

_NUMERIC_RE = re.compile(r"^[\d\s.,+\-]+$")
_SPACE_RE = re.compile(r"\s+")


def normalize_header_text(text: str) -> str:
    value = (text or "").lower().replace("\n", " ")
    value = _SPACE_RE.sub(" ", value).strip()
    return value


def cell_looks_like_data(text: str) -> bool:
    """Чисто числовая ячейка — скорее данные, не заголовок."""
    t = (text or "").strip().replace(" ", "").replace(",", ".")
    if not t:
        return False
    if _NUMERIC_RE.match(t) and any(ch.isdigit() for ch in t):
        # длинное число или число с точкой
        digits = sum(1 for ch in t if ch.isdigit())
        return digits >= 2
    return False


def score_header_row(cell_texts: List[str]) -> float:
    if not cell_texts:
        return 0.0
    filled = [c for c in cell_texts if c and str(c).strip()]
    if not filled:
        return 0.0
    fill_ratio = len(filled) / max(len(cell_texts), len(filled))
    score = fill_ratio * 10.0
    hits = 0
    for text in filled:
        norm = normalize_header_text(str(text))
        if cell_looks_like_data(norm):
            score -= 3.0
            continue
        for synonyms in HEADER_FIELD_SYNONYMS.values():
            if any(s in norm for s in synonyms):
                hits += 1
                score += 8.0
                break
    if hits == 0:
        score -= 5.0
    return score


def map_columns(header_cells: List[dict]) -> Dict[str, int]:
    """field_name → индекс колонки (0-based)."""
    mapping: Dict[str, int] = {}
    for idx, cell in enumerate(header_cells):
        norm = normalize_header_text(str(cell.get("text", "")))
        if not norm:
            continue
        for field, synonyms in HEADER_FIELD_SYNONYMS.items():
            if field in mapping:
                continue
            if any(s in norm for s in synonyms):
                mapping[field] = idx
    return mapping


def is_smeta_column_map(column_map: Dict[str, int]) -> bool:
    """Есть ли признаки сметной шапки (ед/кол/цена/сумма)."""
    return any(k in column_map for k in ("unit", "qty", "price", "sum"))


def two_column_map(cell_count: int) -> Dict[str, int]:
    """Типичная Word-таблица: пункт | содержание."""
    if cell_count >= 2:
        return {"name": 0, "content": 1}
    return {"name": 0}


def detect_header_row(
    table_rows: List[Tuple[int, List[dict]]],
    *,
    scan_limit: int = 15,
) -> Optional[Tuple[int, List[dict], Dict[str, int]]]:
    """
    table_rows: [(line_number, cells), ...] в порядке документа.
    Возвращает (line_number шапки, cells шапки, mapping полей).
    """
    if not table_rows:
        return None

    col_counts = [len(cells) for _, cells in table_rows[:scan_limit]]
    modal_cols = max(set(col_counts), key=col_counts.count) if col_counts else 0

    candidates = table_rows[:scan_limit]
    best: Optional[Tuple[float, int, List[dict]]] = None
    for line_number, cells in candidates:
        texts = [str(c.get("text", "")) for c in cells]
        sc = score_header_row(texts)
        if best is None or sc > best[0]:
            best = (sc, line_number, cells)

    if best and best[0] >= 12.0:
        _, line_number, cells = best
        column_map = map_columns(cells)
        if is_smeta_column_map(column_map):
            return line_number, cells, column_map

    # Двухколоночные таблицы (ТЗ Word): пункт + текст
    if modal_cols == 2:
        header_ln = table_rows[0][0]
        header_cells = [
            {"text": "Пункт", "column_letter": "A"},
            {"text": "Содержание", "column_letter": "B"},
        ]
        return header_ln, header_cells, two_column_map(2)

    # fallback: raw — шапка = первая «шапочная» строка или первая строка
    if best and best[0] >= 5.0:
        _, line_number, cells = best
        return line_number, cells, map_columns(cells)

    line_number, cells = max(candidates, key=lambda x: len(x[1]))
    return line_number, cells, map_columns(cells)


def build_row_values(
    cells: List[dict],
    column_map: Dict[str, int],
    header_cells: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """Собирает именованные значения строки."""
    texts = [str(c.get("text", "")).strip() for c in cells]
    values: Dict[str, Any] = {}
    for field, col_idx in column_map.items():
        if 0 <= col_idx < len(texts) and texts[col_idx]:
            values[field] = texts[col_idx]
    raw: List[Dict[str, str]] = []
    for idx, cell in enumerate(cells):
        label = ""
        if header_cells and idx < len(header_cells):
            label = str(header_cells[idx].get("text", "")).strip()
        raw.append({
            "col": cell.get("column_letter") or f"col{idx + 1}",
            "header": label,
            "text": str(cell.get("text", "")).strip(),
        })
    values["_raw_cells"] = raw
    return values
