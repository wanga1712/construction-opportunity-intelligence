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
from typing import Dict, List, Optional

from .smeta_forma_4b import (
    _num,
    _sheet_members,
    _sheet_rows,
    _shared_strings,
    _unit_of,
)

HEADER_PATTERNS = {
    "name": re.compile(r"наименован|описан|материал|товар|позиц", re.IGNORECASE),
    "unit": re.compile(r"ед\.?\s*изм|единиц", re.IGNORECASE),
    "qty": re.compile(r"кол-?во|количеств|объ[её]м", re.IGNORECASE),
    "price": re.compile(r"цена", re.IGNORECASE),
    "total": re.compile(r"стоимост|сумма|итого", re.IGNORECASE),
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
    mapping: Dict[str, str] = {}
    for column, text in cells.items():
        for field, pattern in HEADER_PATTERNS.items():
            if field not in mapping and pattern.search(str(text or "")):
                mapping[field] = column
    if "name" in mapping and ({"qty", "price", "total"} & set(mapping)):
        return mapping
    return None


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
            mapping: Optional[Dict[str, str]] = None
            quoted = False
            for row_no, cells in _sheet_rows(zf, member, strings):
                if mapping is None:
                    mapping = map_header(cells)
                    continue
                name = str(cells.get(mapping["name"]) or "").strip()
                if not name:
                    continue
                quantity = _num(cells.get(mapping.get("qty", "")))
                price = _num(cells.get(mapping.get("price", "")))
                total = _num(cells.get(mapping.get("total", "")))
                if not any(value for value in (quantity, price, total)):
                    continue
                unit = _unit_of(str(cells.get(mapping.get("unit", "")) or "")) or ""
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
                quoted = True
            if not quoted:
                mapping = None
    return facts
