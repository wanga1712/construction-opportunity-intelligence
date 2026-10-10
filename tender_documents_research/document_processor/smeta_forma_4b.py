"""Deterministic reader for the Smeta.RU construction estimate form ("Форма 4б").

Why: the generic matcher feeds the model a flat dump of worksheet cells, so
quantity / unit price / total cannot be told apart (the model returned quotes
like "1354 1010 шт. шт." and empty found_facts). This reader uses the estimate
column layout instead of a flat dump.

Verified column map (checked by arithmetic on independent rows):
  A = position number      B = norm code        C = name of work/material
  D = unit of measure (optionally with a multiplier: "100 шт." / "шт." / "%")
  E = volume               F = unit price
  I = cost at base level = quantity * unit price
  J = transition index     K = cost at current level

Material lines carry D/F/I/K, and quantity = I / F.
Stdlib only (zip + XML): must run where openpyxl is unavailable.
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import xml.etree.ElementTree as ET

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_CELL_RE = re.compile(r"([A-Z]+)")
_NUM_RE = re.compile(r"[\d\s\u00a0]+[.,]?\d*")

#: Sheets that identify the Smeta.RU estimate family.
MARKER_SHEETS = frozenset({"SmtRes", "EtalonRes", "Source"})

#: Default term -> canonical category mapping (callers may override).
#: Keys mirror the active commercial registry (crm_product_categories,
#: semantic_type=COMMERCIAL_CATEGORY, lifecycle ACTIVE/ACTIVE_AI_ONLY).
CATEGORY_TERMS: Dict[str, Tuple[str, ...]] = {
    "lighting": (
        "светильник", "лампа", "светодиод", "прожектор", "освещ",
        "светотехник", " led",
    ),
    "cable_products": (
        "кабель", "провод ", "кабельная продукция", "ввг", "вббшв",
        "кпсэ", "пугнп", "кабельн",
    ),
    "cable_support_systems": (
        "кабеленесущ", "кабельный лоток", "проволочный лоток", "кабель-канал",
        "кабельная трасса", "лоток металлический", "лоток перфорированный",
    ),
    "composite_structures": (
        "композит", "стеклопласт", "полимербетон", "композитн",
    ),
    "computers": (
        "ноутбук", "моноблок", "системный блок", "сервер", "монитор",
        "клавиатур", "мышь", "мышк", "принтер", "мфу", "сканер",
        "коммутатор", "маршрутизатор", "планшет", "персональн",
        "вычислительн", "интерактивная доска", "проектор", "тонкий клиент",
    ),
    "curbstone": (
        "бордюр", "бортовой камень", "поребрик", "бортовые камни",
    ),
    "drainage_water_management": (
        "дренаж", "ливнев", "водоотвод", "дождеприемник", "трап",
        "лоток водоотводный", "канал водоотводный",
    ),
    "flooring": (
        "линолеум", "керамогранит", "плитка", "ламинат", "паркет",
        "ковролин", "плинтус", "напольн", "покрытие пола", "наливной пол",
    ),
    "waterproofing": (
        "гидроизол", "мембран", "мастик", "рубероид", "наплавляем",
        "праймер", "гидрофоб", "гидростеклоизол", "проникающ",
    ),
    "waterproofing_concrete_repair": (
        "ремонтный состав", "безусадочн", "инъекционн", "гидрофобиз",
        "остановка протеч",
    ),
    "structural_reinforcement": (
        "арматур", "углеволокн", "углеродн", "фибра", "хомут",
    ),
}


@dataclass
class SmetaFact:
    """One documentary material line with provenance."""

    row: int
    sheet: str
    category_code: str
    product_name_raw: str
    quantity_value: Optional[float]
    quantity_unit: str
    unit_price_value: Optional[float]
    total_price_value: Optional[float]
    base_total_value: Optional[float]
    source_quote: str
    confidence: float = 0.95


def _num(value: Any) -> Optional[float]:
    try:
        text = str(value).replace(" ", "").replace("\u00a0", "").replace(",", ".")
        return float(text)
    except (TypeError, ValueError):
        return None


def xlsx_sheet_names(path: str | Path) -> List[str]:
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("xl/workbook.xml"))
    return [sheet.get("name") or "" for sheet in root.iter(f"{_NS}sheet")]


def detect_forma_4b(sheet_names: Iterable[str]) -> bool:
    return MARKER_SHEETS.issubset({str(name) for name in sheet_names})


def _shared_strings(zf: zipfile.ZipFile) -> List[str]:
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [
        "".join(node.text or "" for node in item.iter(f"{_NS}t"))
        for item in root.findall(f"{_NS}si")
    ]


def _sheet_rows(zf: zipfile.ZipFile, member: str, strings: List[str]):
    root = ET.fromstring(zf.read(member))
    for row in root.iter(f"{_NS}row"):
        cells: Dict[str, str] = {}
        for cell in row.findall(f"{_NS}c"):
            match = _CELL_RE.match(cell.get("r") or "")
            value = cell.find(f"{_NS}v")
            if not match or value is None or value.text is None:
                continue
            raw = value.text
            cells[match.group(1)] = (
                strings[int(raw)] if raw.isdigit() and int(raw) < len(strings) else raw
            )
        yield int(row.get("r") or 0), cells


def _category_of(name: str, terms: Dict[str, Tuple[str, ...]]) -> Optional[str]:
    """Most specific term wins (longest match), so "кабельный лоток" is not
    swallowed by the broader "кабель" needle."""
    lowered = name.lower()
    best_code: Optional[str] = None
    best_len = 0
    for code, needles in terms.items():
        for needle in needles:
            if needle in lowered and len(needle) > best_len:
                best_code, best_len = code, len(needle)
    return best_code


def _unit_of(cell: str) -> Optional[str]:
    """Unit-of-measure text from a D cell ("шт." / "100 шт." / "м2"), or None."""
    if not cell or cell == "%":
        return None
    unit = _NUM_RE.sub("", cell).strip()
    return unit or None


def _sheet_members(zf: zipfile.ZipFile) -> List[Tuple[str, str]]:
    """Workbook sheet order -> worksheet member, resolved via workbook rels.

    Sorting ``xl/worksheets/sheet*.xml`` lexicographically is wrong for >9 sheets
    (sheet10 < sheet2), which silently broke estimates with many sheets.
    """
    rels_ns = "{http://schemas.openxmlformats.org/package/2006/relationships}"
    targets: Dict[str, str] = {}
    try:
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        for rel in rels.iter(f"{rels_ns}Relationship"):
            target = rel.get("Target") or ""
            if "worksheets/" in target:
                targets[rel.get("Id") or ""] = "xl/" + target.lstrip("/").replace("xl/", "", 1)
    except KeyError:
        return []
    r_id = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    out: List[Tuple[str, str]] = []
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    for sheet in workbook.iter(f"{_NS}sheet"):
        member = targets.get(sheet.get(r_id) or "")
        if member:
            out.append((sheet.get("name") or "", member))
    return out


def read_estimate(
    path: str | Path,
    *,
    terms: Dict[str, Tuple[str, ...]] | None = None,
) -> List[SmetaFact]:
    """Return documentary facts for every material line matching ``terms``."""
    terms = dict(terms or CATEGORY_TERMS)
    facts: List[SmetaFact] = []
    with zipfile.ZipFile(path) as zf:
        strings = _shared_strings(zf)
        names: List[str] = []
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        for sheet in workbook.iter(f"{_NS}sheet"):
            names.append(sheet.get("name") or "")
        members = _sheet_members(zf)
        if not members:
            return facts
        main_sheet, main_member = members[0]
        for row_no, cells in _sheet_rows(zf, main_member, strings):
            name = str(cells.get("C") or "").strip()
            if not name:
                continue
            category = _category_of(name, terms)
            if not category:
                continue
            unit_cell = str(cells.get("D") or "").strip()
            unit = _unit_of(unit_cell)
            if not unit:
                continue
            price = _num(cells.get("F"))
            base_total = _num(cells.get("I"))
            if not price or not base_total:
                continue
            quote = " | ".join(
                f"{key}={cells[key]}"
                for key in ("A", "B", "C", "D", "E", "F", "I", "J", "K")
                if key in cells
            )
            facts.append(
                SmetaFact(
                    row=row_no,
                    sheet=main_sheet,
                    category_code=category,
                    product_name_raw=name,
                    quantity_value=round(base_total / price, 6),
                    quantity_unit=unit,
                    unit_price_value=price,
                    total_price_value=_num(cells.get("K")),
                    base_total_value=base_total,
                    source_quote=quote,
                )
            )
    return facts


def main(argv: List[str]) -> int:
    if not argv:
        print("usage: smeta_forma_4b.py <estimate.xlsx> [more.xlsx ...]")
        return 2
    for raw in argv:
        path = Path(raw)
        names = xlsx_sheet_names(path)
        print("FILE", path.name, "FORMA_4B", detect_forma_4b(names))
        for fact in read_estimate(path):
            print(json.dumps(asdict(fact), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
