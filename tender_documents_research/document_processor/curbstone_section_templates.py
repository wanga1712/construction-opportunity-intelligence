"""CURBSTONE_SECTION_TEMPLATES_V1 (3A Phase 2) — шаблонный слой бортового камня.

Данные `curbstone` приходят из двух источников:

  * xlsx-сметы/ведомости без текстовых маркеров разделов (строки `A=… B=…`);
  * OCR-PDF, где есть `page_or_sheet` вида `page_19_table_1`.

Поэтому слой использует два уровня identity:

  1. текстовый маркер «Раздел/Глава/Секция/Участок/Лот N <Название>»,
     если он есть в `source_quote` (будущие документы/ручные сметы);
  2. fallback-контейнер `page_or_sheet` (`page_19_table_1`, `table_2`),
     когда маркера нет, но лист/страница известны.

Строки без маркера и без страницы честно уходят в `RESIDUE` — выдуманных
разделов не создаём. В сумму входят только canonical summarizable-материалы.
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

CURBSTONE_CODE_PREFIX = "curbstone"
COVERAGE_MIN = 0.9

_RAZDEL_RE = re.compile(
    r"(?:^|\|)\s*раздел\s*№?\s*([0-9]+(?:\.[0-9]+)*)\s*[.:]?\s*([^\n|]{0,90})",
    re.IGNORECASE,
)
_GLAVA_RE = re.compile(
    r"(?:^|\|)\s*глав[аы]\s*№?\s*([0-9]+(?:\.[0-9]+)*)\s*[.:]?\s*([^\n|]{0,90})",
    re.IGNORECASE,
)
_SEKCIA_RE = re.compile(
    r"(?:^|\|)\s*секци[яи]\s*№?\s*([0-9]+(?:\.[0-9]+)*)\s*[.:]?\s*([^\n|]{0,90})",
    re.IGNORECASE,
)
_UCHASTOK_RE = re.compile(
    r"(?:^|\|)\s*участок\s*№?\s*([0-9]+(?:\.[0-9]+)*)\s*[.:]?\s*([^\n|]{0,90})",
    re.IGNORECASE,
)
_LOT_RE = re.compile(
    r"(?:^|\|)\s*лот\s*№?\s*([0-9]+(?:\.[0-9]+)*)\s*[.:]?\s*([^\n|]{0,90})",
    re.IGNORECASE,
)
_TOTAL_LABEL_RE = re.compile(r"^\s*(итого|всего)\b", re.IGNORECASE)


@dataclass
class CurbstoneMarker:
    kind: str                 # razdel | glava | sekcia | uchastok | lot
    number: str
    name: Optional[str] = None

    def code(self, sheet: Optional[str] = None, doc_id: Any = None) -> str:
        parts = [CURBSTONE_CODE_PREFIX]
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


def parse_curbstone_marker(*texts: Any) -> Optional[CurbstoneMarker]:
    for text in texts:
        if not text:
            continue
        for cell in _cells(text):
            for kind, regex in (
                ("razdel", _RAZDEL_RE),
                ("glava", _GLAVA_RE),
                ("sekcia", _SEKCIA_RE),
                ("uchastok", _UCHASTOK_RE),
                ("lot", _LOT_RE),
            ):
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
                return CurbstoneMarker(kind=kind, number=m.group(1), name=name)
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


def _page_code(sheet: str) -> str:
    return f"{CURBSTONE_CODE_PREFIX}::{sheet}::sheet"


def build_curbstone_sections(
    rows: Sequence[Dict[str, Any]],
    *,
    coverage_min: float = COVERAGE_MIN,
    page_fallback: bool = True,
) -> Dict[str, Any]:
    """Собрать разделы/страницы бортового камня (детерминированно, без БД)."""
    sections: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    current: Optional[str] = None
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
        sheet = row.get("page_or_sheet") or row.get("sheet")
        sheet = str(sheet).strip() if sheet else None
        marker = parse_curbstone_marker(row.get("source_quote"))
        if marker is None:
            marker = parse_curbstone_marker(
                row.get("product_name_raw"), row.get("product_name_normalized")
            )
        if marker is not None:
            current = marker.code(sheet, row.get("source_document_id"))
            _section(current, marker.name, sheet, marker.kind, marker.number)
        elif page_fallback and sheet and current is None:
            # OCR-оценки без маркеров: лист/страница — честный контейнер.
            current = _page_code(sheet)
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
        "template": "curbstone_section_templates_v1",
    }
