"""SHEET_SECTION_TEMPLATES_V1 — общий движок разделов для «листовых» категорий.

Используется curbstone и drainage_water_management (и следующими категориями
с той же формой данных):

  1. текстовый маркер «Раздел/Глава/Секция/Участок/Лот N <Название>»;
  2. identity с листом (`<prefix>::<sheet>::...`) или номером документа
     (`<prefix>::docN::...`), чтобы одноимённые разделы не сливались;
  3. fallback-контейнер `page_or_sheet` для OCR-оценок без маркеров;
  4. numeric fake names отбрасываются;
  5. строки без маркера и без страницы — честный RESIDUE;
  6. в сумму только canonical summarizable-материалы.

Модуль read-only: не пишет в БД и не трогает scoring / medal / queue.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from .section_detector import (
    SECTION_RESIDUE,
    TOTAL_COMPUTED,
    TOTAL_COMPUTED_UNRELIABLE,
    is_summarizable,
)

COVERAGE_MIN = 0.9

_MARKERS = (
    ("razdel", re.compile(
        r"(?:^|\|)\s*раздел\s*№?\s*([0-9]+(?:\.[0-9]+)*)\s*[.:]?\s*([^\n|]{0,90})",
        re.IGNORECASE)),
    ("glava", re.compile(
        r"(?:^|\|)\s*глав[аы]\s*№?\s*([0-9]+(?:\.[0-9]+)*)\s*[.:]?\s*([^\n|]{0,90})",
        re.IGNORECASE)),
    ("sekcia", re.compile(
        r"(?:^|\|)\s*секци[яи]\s*№?\s*([0-9]+(?:\.[0-9]+)*)\s*[.:]?\s*([^\n|]{0,90})",
        re.IGNORECASE)),
    ("uchastok", re.compile(
        r"(?:^|\|)\s*участок\s*№?\s*([0-9]+(?:\.[0-9]+)*)\s*[.:]?\s*([^\n|]{0,90})",
        re.IGNORECASE)),
    ("lot", re.compile(
        r"(?:^|\|)\s*лот\s*№?\s*([0-9]+(?:\.[0-9]+)*)\s*[.:]?\s*([^\n|]{0,90})",
        re.IGNORECASE)),
)
_TOTAL_LABEL_RE = re.compile(r"^\s*(итого|всего)\b", re.IGNORECASE)


@dataclass
class SheetMarker:
    kind: str
    number: str
    name: Optional[str] = None

    def code(self, prefix: str, sheet: Optional[str] = None, doc_id: Any = None) -> str:
        parts = [prefix]
        if sheet:
            parts.append(str(sheet))
        elif doc_id is not None:
            # Без листа один и тот же «Раздел 1» из разных документов
            # не должен сливаться в один контейнер.
            parts.append(f"doc{doc_id}")
        parts.append(f"{self.kind} {self.number}")
        return "::".join(parts)


def _cells(text: Any) -> List[str]:
    out: List[str] = []
    for part in str(text or "").split("|"):
        part = part.strip()
        if not part:
            continue
        if len(part) > 2 and part[1] == "=" and part[0].isalpha():
            part = part[2:].strip()
        if part:
            out.append(part)
    return out


def _clean_name(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    text = re.sub(r"\s+", " ", str(raw).strip(" .:;-—\t"))
    if not text:
        return None
    if re.fullmatch(r"[\d\s.,]+", text):
        return None
    low = text.lower()
    if low.startswith(("итого", "всего")) or low in (
        "раздел", "глава", "секция", "участок", "лот",
    ):
        return None
    return text[:90]


def parse_sheet_marker(*texts: Any) -> Optional[SheetMarker]:
    for text in texts:
        if not text:
            continue
        for cell in _cells(text):
            for kind, regex in _MARKERS:
                m = regex.search(cell)
                if not m:
                    continue
                name = _clean_name(m.group(2))
                if not name:
                    cells = _cells(text)
                    try:
                        idx = cells.index(cell)
                    except ValueError:
                        idx = -1
                    if 0 <= idx < len(cells) - 1:
                        name = _clean_name(cells[idx + 1])
                return SheetMarker(kind=kind, number=m.group(1), name=name)
    return None


def _row_summarizable(row: Dict[str, Any]) -> bool:
    return is_summarizable(
        entity_type=row.get("entity_type") or "PRODUCT",
        layout_status=row.get("layout_status"),
        quantity_value=row.get("quantity_value"),
        unit_normalized=row.get("quantity_unit_normalized"),
        name=row.get("product_name_normalized") or row.get("product_name_raw"),
    )


def _row_total(row: Dict[str, Any]) -> Optional[float]:
    try:
        value = row.get("total_price_value")
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _page_code(prefix: str, sheet: str) -> str:
    return f"{prefix}::{sheet}::sheet"


def build_sheet_sections(
    rows: Sequence[Dict[str, Any]],
    *,
    prefix: str,
    template: str,
    coverage_min: float = COVERAGE_MIN,
    page_fallback: bool = True,
) -> Dict[str, Any]:
    """Собрать разделы/страницы категории (детерминированно, без БД)."""
    sections: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    current: Optional[str] = None
    current_doc: Any = None
    current_is_sheet = False
    residue: List[Dict[str, Any]] = []

    def _section(code: str, name: Optional[str], sheet: Optional[str],
                 kind: str, number: Optional[str]) -> Dict[str, Any]:
        if code not in sections:
            sections[code] = {
                "section_code": code,
                "section_name": name or number or (sheet or code),
                "page_or_sheet": sheet,
                "marker_kind": kind,
                "marker_number": number,
                "shifrs": [],
                "materials": [],
                "computed_sum": 0.0,
                "summarizable_rows": 0,
                "total_rows": 0,
                "aggregate_rows": 0,
                "total_value": None,
                "total_source": None,
            }
            order.append(code)
        return sections[code]

    for row in rows or []:
        doc_id = row.get("source_document_id")
        # Смена документа обрывает наследование раздела: строки другого файла
        # не должны попадать в «Раздел N» предыдущего документа.
        if doc_id is not None:
            if current_doc is not None and doc_id != current_doc:
                current = None
                current_is_sheet = False
            current_doc = doc_id
        sheet = row.get("page_or_sheet") or row.get("sheet")
        sheet = str(sheet).strip() if sheet else None
        marker = parse_sheet_marker(row.get("source_quote"))
        if marker is None:
            marker = parse_sheet_marker(
                row.get("product_name_raw"), row.get("product_name_normalized")
            )
        if marker is not None:
            current = marker.code(prefix, sheet, doc_id)
            current_is_sheet = False
            _section(current, marker.name, sheet, marker.kind, marker.number)
        elif page_fallback and sheet:
            page_code = _page_code(prefix, sheet)
            # Новый лист/страница — новый контейнер; строки не должны
            # наследовать предыдущую страницу того же документа.
            if current is None or (current_is_sheet and current != page_code):
                current = page_code
                current_is_sheet = True
                _section(current, sheet, sheet, "sheet", None)

        if current is None:
            residue.append(row)
            continue

        section = sections[current]
        name = str(row.get("product_name_raw") or "")
        if _TOTAL_LABEL_RE.match(name):
            section["aggregate_rows"] += 1
            value = _row_total(row)
            if value is not None and section["total_source"] is None:
                section["total_value"] = value
                section["total_source"] = "SECTION_TOTAL"
            continue
        if not _row_summarizable(row):
            continue
        section["summarizable_rows"] += 1
        value = _row_total(row)
        if value is not None:
            section["computed_sum"] += value
            section["total_rows"] += 1
        section["materials"].append(row)

    out: List[Dict[str, Any]] = []
    for code in order:
        section = sections[code]
        coverage = (
            section["total_rows"] / section["summarizable_rows"]
            if section["summarizable_rows"] else 0.0
        )
        section["coverage"] = round(coverage, 4)
        section["material_count"] = len(section["materials"])
        if section["total_source"] != "SECTION_TOTAL":
            section["total_value"] = (
                round(section["computed_sum"], 2) if section["summarizable_rows"] else None
            )
            section["total_source"] = (
                TOTAL_COMPUTED_UNRELIABLE
                if (section["aggregate_rows"] or coverage < coverage_min)
                else TOTAL_COMPUTED
            )
        out.append(section)

    return {
        "sections": out,
        "residue": {"rows": residue, "count": len(residue)},
        "residue_code": SECTION_RESIDUE,
        "template": template,
    }
