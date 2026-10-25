"""Header-driven reader for estimate-like xlsx files (any template).

«Форма 4б» has a fixed layout, but most estimates use other templates. This
reader finds the table header row and maps columns by their Russian captions
(Наименование / Ед. изм. / Кол-во / Цена / Стоимость), then reads material rows
below it. Unknown layouts are reported so they can be supported later.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .smeta_forma_4b import (
    _num,
    _sheet_members,
    _sheet_rows,
    _shared_strings,
    _unit_of,
)
from .embedded_extraction import normalize_unit, split_quantity_unit
from .estimate_value_mapping import quantity_for_unit, select_arithmetic_pair

HEADER_PATTERNS = {
    "name": re.compile(r"наименован|описан|материал|товар|позиц", re.IGNORECASE),
    "unit": re.compile(r"ед\.?\s*изм|единиц", re.IGNORECASE),
    "qty": re.compile(r"кол-?во|количеств|объ[её]м", re.IGNORECASE),
    "price": re.compile(r"цена", re.IGNORECASE),
    "total": re.compile(r"стоимост|сумма|итого|всего", re.IGNORECASE),
}


@dataclass
class TableFact:
    row: int
    sheet: str
    product_name_raw: str
    quantity_value: Optional[float]
    quantity_unit: str
    unit_price_value: Optional[float]
    total_price_value: Optional[float]
    source_quote: str
    confidence: float = 0.8


def map_header(cells: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Column letters by caption; needs a name column plus any numeric column."""
    candidates = header_candidates(cells)
    if not candidates:
        return None
    return {field: columns[0] for field, columns in candidates.items() if columns}


def header_candidates(cells: Dict[str, str]) -> Optional[Dict[str, list[str]]]:
    """Retain every caption-matched value column for arithmetic selection."""
    mapping: Dict[str, list[str]] = {}
    for column, text in cells.items():
        for field, pattern in HEADER_PATTERNS.items():
            if pattern.search(str(text or "")):
                mapping.setdefault(field, []).append(column)
    if mapping.get("name") and ({"qty", "price", "total"} & set(mapping)):
        return mapping
    return None


def _column_number(column: str) -> int:
    value = 0
    for char in str(column).upper():
        if "A" <= char <= "Z":
            value = value * 26 + ord(char) - 64
    return value


def _quantity_from_cell(cell: str) -> Optional[float]:
    value = _num(cell)
    if value is not None:
        return value
    parsed = split_quantity_unit(cell)
    return parsed[0] if parsed else None


def _unit_for_row(
    cells: Dict[str, str],
    unit_columns: Sequence[str],
    quantity_column: Optional[str],
    quantity_cell: str,
) -> str:
    for column in unit_columns:
        unit = _unit_of(str(cells.get(column) or ""))
        if unit:
            return unit
    parsed = split_quantity_unit(quantity_cell)
    if parsed and parsed[1]:
        return parsed[1]
    if quantity_column is None:
        return ""
    quantity_index = _column_number(quantity_column)
    candidates = []
    for column, text in cells.items():
        unit = _unit_of(str(text or ""))
        if unit:
            candidates.append((abs(_column_number(column) - quantity_index), column, unit))
    return min(candidates)[2] if candidates else ""


def template_signature(path: str | Path) -> str:
    """Stable fingerprint of a layout we could not parse: sheet names + headers."""
    with zipfile.ZipFile(path) as zf:
        strings = _shared_strings(zf)
        members = _sheet_members(zf)
        names = "|".join(name for name, _ in members)
        captions: List[str] = []
        for _sheet, member in members[:1]:
            for _row, cells in _sheet_rows(zf, member, strings):
                for text in cells.values():
                    lowered = str(text).lower()
                    for field, pattern in HEADER_PATTERNS.items():
                        if pattern.search(lowered) and field not in captions:
                            captions.append(field)
                if len(captions) >= 3:
                    break
    return (names + "::" + ",".join(sorted(captions)))[:200]


def read_tables(path: str | Path) -> List[TableFact]:
    """All material rows across every sheet that has a recognisable header."""
    facts: List[TableFact] = []
    with zipfile.ZipFile(path) as zf:
        strings = _shared_strings(zf)
        for sheet_name, member in _sheet_members(zf):
            mapping: Optional[Dict[str, list[str]]] = None
            for row_no, cells in _sheet_rows(zf, member, strings):
                if mapping is None:
                    mapping = header_candidates(cells)
                    continue
                name_column = mapping["name"][0]
                name = str(cells.get(name_column) or "").strip()
                if not name:
                    continue
                quantity_column = None
                quantity_cell = ""
                quantity = None
                for column in mapping.get("qty", []):
                    candidate = str(cells.get(column) or "")
                    candidate_quantity = _quantity_from_cell(candidate)
                    if candidate_quantity is not None:
                        quantity_column = column
                        quantity_cell = candidate
                        quantity = candidate_quantity
                        break
                unit = _unit_for_row(
                    cells,
                    mapping.get("unit", []),
                    quantity_column,
                    quantity_cell,
                )
                normalized_unit = normalize_unit(unit)[0] if unit else None
                quantity = quantity_for_unit(quantity, normalized_unit)

                prices = []
                for column in mapping.get("price", []):
                    value = _num(cells.get(column))
                    if value is not None:
                        prices.append((column, value))
                totals = []
                for column in mapping.get("total", []):
                    value = _num(cells.get(column))
                    if value is not None:
                        totals.append((column, value))
                pair = select_arithmetic_pair(quantity, prices, totals)
                price = pair[1] if pair else None
                total = pair[3] if pair else None
                if quantity is None and price is None and total is None:
                    continue
                quote = " | ".join(f"{column}={cells[column]}" for column in sorted(cells))
                facts.append(
                    TableFact(
                        row=row_no,
                        sheet=sheet_name,
                        product_name_raw=name,
                        quantity_value=quantity,
                        quantity_unit=unit,
                        unit_price_value=price,
                        total_price_value=total,
                        source_quote=quote[:500],
                    )
                )
    return facts
