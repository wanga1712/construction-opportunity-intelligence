"""Header-driven reader for estimate-like xlsx files (any template).

«Форма 4б» has a fixed layout, but most estimates use other templates. This
reader finds the table header row and maps columns by their Russian captions
(Наименование / Ед. изм. / Кол-во / Цена / Стоимость), then reads material rows
below it. Unknown layouts are reported so they can be supported later.
"""
from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
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
    "price": re.compile(
        r"(?:цена|цену|цене|за\s+ед\.?\s*иниц)", re.IGNORECASE
    ),
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
    quantity_raw: Optional[str] = None
    unit_raw: Optional[str] = None
    unit_price_raw: Optional[str] = None
    total_raw: Optional[str] = None
    layout_status: Optional[str] = None
    header_path: Optional[Dict[str, str]] = None


def map_header(cells: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Column letters by caption; needs a name column plus any numeric column."""
    candidates = header_candidates(cells)
    if not candidates:
        return None
    return {field: columns[0] for field, columns in candidates.items() if columns}


def header_candidates(
    cells: Dict[str, str], *, allow_partial: bool = False
) -> Optional[Dict[str, list[str]]]:
    """Retain every caption-matched value column for arithmetic selection."""
    mapping: Dict[str, list[str]] = {}
    for column, text in cells.items():
        for field, pattern in HEADER_PATTERNS.items():
            if pattern.search(str(text or "")):
                mapping.setdefault(field, []).append(column)
    # A footnote can contain every caption keyword in one explanatory cell.
    # It is not a table header and must not replace the real column mapping.
    numeric_columns = {
        column
        for field in ("qty", "price", "total")
        for column in mapping.get(field, ())
    }
    if mapping.get("name") and numeric_columns.difference(mapping["name"]):
        return mapping
    # Estimates often put a broad caption on one row ("Стоимость работ"),
    # then split it into "за единицу" and "всего" on the next row. Keep that
    # second row so read_tables can merge the precise child columns.
    if allow_partial and {"price", "total"}.issubset(mapping):
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


def _select_row_values(
    cells: Dict[str, str],
    mapping: Dict[str, list[str]],
    unit_normalized: Optional[str],
    *,
    allow_fractional_quantity: bool = False,
) -> Dict[str, object]:
    """Select normalized values and their raw cells from the same columns."""
    qty_column = None
    qty_raw = None
    qty_fallback = None
    quantity = None
    for column in mapping.get("qty", []):
        raw = str(cells.get(column) or "")
        if raw.strip() and qty_fallback is None:
            qty_fallback = raw
        parsed = _quantity_from_cell(raw)
        if parsed is not None:
            qty_column, qty_raw, quantity = column, raw, parsed
            break
    if qty_raw is None:
        qty_raw = qty_fallback
    if not allow_fractional_quantity:
        quantity = quantity_for_unit(quantity, unit_normalized)

    prices: Dict[str, tuple[float, str]] = {}
    for column in mapping.get("price", []):
        raw = str(cells.get(column) or "")
        parsed = _num(raw)
        if parsed is not None:
            prices[column] = (parsed, raw)
    totals: Dict[str, tuple[float, str]] = {}
    for column in mapping.get("total", []):
        raw = str(cells.get(column) or "")
        parsed = _num(raw)
        if parsed is not None:
            totals[column] = (parsed, raw)

    pair = select_arithmetic_pair(
        quantity,
        [(column, value[0]) for column, value in prices.items()],
        [(column, value[0]) for column, value in totals.items()],
    )
    rate_only = bool(pair is None and prices and qty_column is None and not totals)
    if pair is not None:
        price_column, price, total_column, total, _delta = pair
    else:
        price_column = max(prices, key=_column_number) if prices else None
        total_column = max(totals, key=_column_number) if totals else None
        price = prices[price_column][0] if price_column else None
        total = None
    return {
        "quantity": quantity,
        "quantity_raw": qty_raw,
        "quantity_column": qty_column,
        "price": price,
        "unit_price_raw": prices[price_column][1] if price_column else None,
        "price_column": price_column,
        "total": total,
        "total_raw": totals[total_column][1] if total_column else None,
        "total_column": total_column,
        "pair": pair,
        "rate_only": rate_only,
    }


def _unit_for_row(
    cells: Dict[str, str],
    unit_columns: Sequence[str],
    quantity_column: Optional[str],
    quantity_cell: str,
) -> str:
    for column in unit_columns:
        raw_unit = str(cells.get(column) or "").strip()
        if _unit_of(raw_unit):
            return raw_unit
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


def _merged_ranges(zf: zipfile.ZipFile, member: str) -> list[tuple[int, int, int, int]]:
    """Return (first_col, last_col, first_row, last_row) for worksheet merges."""
    root = ET.fromstring(zf.read(member))
    ranges = []
    for node in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}mergeCell"):
        match = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", node.get("ref", ""))
        if not match:
            continue
        first, first_row, last, last_row = match.groups()
        ranges.append((_column_number(first), _column_number(last), int(first_row), int(last_row)))
    return ranges


def _grand_estimate_mapping(
    rows: list[tuple[int, Dict[str, str]]],
    index: int,
    merged: Sequence[tuple[int, int, int, int]],
) -> Optional[tuple[Dict[str, list[str]], Dict[str, str]]]:
    """Map the merged, two-level Grand-Smeta header without flattening its meaning."""
    row_no, cells = rows[index]
    columns = {col for first, last, start, end in merged if start <= row_no <= end for col in range(first, last + 1)}
    if not columns or not any("наименован" in str(v).lower() for v in cells.values()):
        return None

    # Expand only merged header captions; data cells remain untouched.
    parent_by_col: Dict[str, str] = {}
    for first, last, start, end in merged:
        if start != row_no or (end == start and last == first):
            continue
        anchor = next((v for c, v in cells.items() if _column_number(c) == first), "")
        for col_no in range(first, last + 1):
            parent_by_col[_column_name(col_no)] = str(anchor or "")
    for col, value in cells.items():
        parent_by_col.setdefault(col, str(value or ""))

    child_cells: Dict[str, str] = {}
    # Keep actual leaf-caption rows and ignore nearby section titles and
    # numeric column-index guides.
    for _, child in rows[index + 1:index + 4]:
        non_numeric = {
            k: str(v) for k, v in child.items()
            if str(v).strip() and not str(v).strip().isdigit()
        }
        joined = " ".join(non_numeric.values()).lower()
        if any(term in joined for term in ("на единиц", "коэффициент", "всего")):
            child_cells.update(non_numeric)
    paths = {
        col: " ".join(part for part in (parent, child_cells.get(col, "")) if part).strip()
        for col, parent in parent_by_col.items()
    }
    lowered_parent = {col: value.lower() for col, value in parent_by_col.items()}
    lowered_path = {col: value.lower() for col, value in paths.items()}
    name_cols = [c for c, v in lowered_parent.items() if "наименован" in v]
    unit_cols = [c for c, v in lowered_parent.items() if "единиц" in v and "измер" in v]
    qty_parent = [c for c, v in lowered_parent.items() if "количеств" in v]
    qty_cols = [c for c in qty_parent if "всего с учетом коэффициентов" in lowered_path.get(c, "")]
    if not qty_cols:
        # A merged quantity group has its final quantity in the rightmost child
        # explicitly labelled as the coefficient-adjusted total.
        qty_cols = [c for c in qty_parent if "всего" in lowered_path.get(c, "")]
    price_cols = [
        c for c, path in lowered_path.items()
        if "стоимост" in lowered_parent.get(c, "")
        and "на единицу" in path
        and "в текущем уровне цен" in path
        and "в базисном уровне цен" not in path
    ]
    if not price_cols:
        price_cols = [
            c for c, path in lowered_path.items()
            if "стоимост" in lowered_parent.get(c, "") and "на единицу" in path
        ]
    total_cols = [
        c for c, path in lowered_path.items()
        if "стоимост" in lowered_parent.get(c, "")
        and "в текущем уровне цен" in path
        and "на единицу" not in path
    ]
    if not (name_cols and unit_cols and qty_cols and price_cols and total_cols):
        return None
    mapping = {
        "name": name_cols[:1], "unit": unit_cols[:1], "qty": qty_cols[-1:],
        "price": price_cols[:1], "total": total_cols[:1],
    }
    return mapping, {col: paths[col] for col in set(sum(mapping.values(), []))}


def _column_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _is_numbered_header_row(cells: Dict[str, str]) -> bool:
    """Skip the conventional 1..N column-index row below estimate headers."""
    values = [str(value).strip() for value in cells.values() if str(value).strip()]
    return len(values) >= 4 and all(value.isdigit() for value in values) and values == [
        str(index) for index in range(1, len(values) + 1)
    ]


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


def read_tables(
    path: str | Path,
    *,
    include_descriptive: bool = False,
) -> List[TableFact]:
    """Read mapped rows, optionally retaining rows without numeric values."""
    facts: List[TableFact] = []
    with zipfile.ZipFile(path) as zf:
        strings = _shared_strings(zf)
        for sheet_name, member in _sheet_members(zf):
            rows = list(_sheet_rows(zf, member, strings))
            merged = _merged_ranges(zf, member)
            mapping: Optional[Dict[str, list[str]]] = None
            active_header_path: Optional[Dict[str, str]] = None
            for row_index, (row_no, cells) in enumerate(rows):
                if active_header_path and _is_numbered_header_row(cells):
                    continue
                grand_mapping = _grand_estimate_mapping(rows, row_index, merged)
                if grand_mapping:
                    mapping, active_header_path = grand_mapping
                    continue
                candidate_mapping = header_candidates(
                    cells, allow_partial=True
                )
                if candidate_mapping:
                    if "name" in candidate_mapping:
                        mapping = candidate_mapping
                        active_header_path = None
                    elif mapping and "price" in candidate_mapping:
                        mapping = {
                            **mapping,
                            "price": candidate_mapping["price"],
                            "total": candidate_mapping["total"],
                        }
                    continue
                if mapping is None:
                    continue
                name_column = mapping["name"][0]
                name = str(cells.get(name_column) or "").strip()
                if not name:
                    continue
                quantity_column = None
                quantity_cell = ""
                for column in mapping.get("qty", []):
                    candidate = str(cells.get(column) or "")
                    if candidate.strip() and not quantity_cell:
                        quantity_cell = candidate
                    if _quantity_from_cell(candidate) is not None:
                        quantity_column = column
                        quantity_cell = candidate
                        break
                unit = _unit_for_row(
                    cells,
                    mapping.get("unit", []),
                    quantity_column,
                    quantity_cell,
                )
                normalized_unit = normalize_unit(unit)[0] if unit else None
                quantity_column = next(
                    (
                        column
                        for column in mapping.get("qty", [])
                        if str(cells.get(column) or "").strip()
                    ),
                    quantity_column,
                )
                allow_fractional_quantity = bool(
                    active_header_path
                    and quantity_column
                    and "коэффициент"
                    in active_header_path.get(quantity_column, "").lower()
                )
                selected = _select_row_values(
                    cells,
                    mapping,
                    normalized_unit,
                    allow_fractional_quantity=allow_fractional_quantity,
                )
                quantity = selected["quantity"]
                quantity_cell = selected["quantity_raw"] or quantity_cell
                price = selected["price"]
                total = selected["total"]
                unit_price_raw = selected["unit_price_raw"]
                total_raw = selected["total_raw"]
                pair = selected["pair"]
                # Keep an observed unit rate even when this row has no total,
                # or when qty×rate does not prove the reported total. The raw
                # quote remains the evidence; the gate can reject inconsistent
                # arithmetic without losing the source price.
                rate_only = bool(selected["rate_only"])
                if rate_only:
                    # Price catalogs / NMCK market-comparison sheets contain
                    # several supplier prices and one final unit rate, but no
                    # procurement quantity.  The rightmost mapped price is the
                    # deterministic result column (for example «НМЦ за
                    # единицу»).  Preserve it as a reference rate without
                    # manufacturing quantity or line total.
                    pass
                if (
                    not include_descriptive
                    and quantity is None
                    and price is None
                    and total is None
                ):
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
                        quantity_raw=quantity_cell or None,
                        unit_raw=unit or None,
                        unit_price_raw=unit_price_raw,
                        total_raw=total_raw,
                        layout_status=(
                            "CONSISTENT"
                            if pair is not None
                            else (
                                "UNIT_RATE_ONLY"
                                if rate_only
                                else (
                                    "INCONSISTENT_LAYOUT"
                                    if (
                                        quantity is not None
                                        and selected["price_column"]
                                        and selected["total_column"]
                                    )
                                    else "PARTIAL_VALUES"
                                )
                            )
                        ),
                        header_path=active_header_path,
                        confidence=0.75 if rate_only else 0.8,
                    )
                )
    return facts
