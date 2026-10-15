"""ROAD_REPAIR_SECTION_TEMPLATES_V1 (Phase 1) — шаблонный слой дорожных смет/ВОР.

Дорожное семейство использует устойчивый ТЕКСТОВЫЙ маркер
«Итого по разделу N <Название>» (и «Глава N. <Название>»), но позиция колонки
нестабильна (AE у 60467, F у 178620), а сметы лежат внутри архивов и PDF/DOCX —
прямого `.gsfx` в `document_files` нет. Поэтому слой работает по строковому
тексту (`source_quote`), а не по номеру колонки и не по типу файла.

Что делает слой:

  * распознаёт раздел по тексту строки (`parse_road_marker`);
  * `section_name` берёт из текста после номера («Земляное полотно», «Дорожная одежда»);
  * identity раздела — лист + номер: `road::<sheet>::razdel N` / `road::<sheet>::glava N`
    (одноимённые разделы из «ПСК»/«Лист1»/«ВКР» не сливаются);
  * шифры `СР-*` / `ЛС-*` / `ОС-*` из колонки B использует как fallback identity;
  * в сумму включает ТОЛЬКО canonical summarizable-материалы
    (`section_detector.is_summarizable`), агрегаты не суммирует;
  * непривязанное честно отдаёт в `RESIDUE`.

Модуль ничего не пишет в БД и не трогает scoring / medal / queue.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .section_detector import (
    SECTION_RESIDUE,
    TOTAL_COMPUTED,
    TOTAL_COMPUTED_UNRELIABLE,
    is_aggregate_row,
    is_summarizable,
)

ROAD_CODE_PREFIX = "road"
COVERAGE_MIN = 0.9

#: «Итого по разделу 13 Подготовка территории строительства»
_RAZDEL_RE = re.compile(
    r"итого\s+по\s+разделу\s*№?\s*([0-9]+(?:\.[0-9]+)*)\s*[.:]?\s*([^\n|]{0,90})",
    re.IGNORECASE,
)
#: «Глава 1. Подготовка территории строительства» / «Глава 2 Земляное полотно»
_GLAVA_RE = re.compile(
    r"глав[аы]\s*№?\s*([0-9]+(?:\.[0-9]+)*)\s*[.:]?\s*([^\n|]{0,90})",
    re.IGNORECASE,
)
#: шифры дорожной сметы: СР-01-01, ЛС-01-01-01, ОС-01-01
_SHIFR_RE = re.compile(r"\b([А-ЯЁA-Z]{2}(?:-\d{2})+)\b")
#: маркер итога/агрегата в строке (для «эта строка — итог раздела»)
_TOTAL_LABEL_RE = re.compile(r"^\s*(итого|всего)\b", re.IGNORECASE)


@dataclass
class RoadMarker:
    kind: str                 # "razdel" | "glava"
    number: str
    name: Optional[str]
    shifr: Optional[str] = None

    def code(self, sheet: Optional[str] = None) -> str:
        """`road::<sheet>::razdel N` (лист обязателен, когда он известен).

        Первичная identity — лист + номер раздела/главы: одноимённые разделы из
        «ПСК» / «Лист1» / «ВКР» не должны сливаться. Шифр (СР/ЛС/ОС) — только
        fallback для строк, где маркер не повторён (см. shifr_to_code).
        """
        parts = [ROAD_CODE_PREFIX]
        if sheet:
            parts.append(str(sheet))
        parts.append(f"{self.kind} {self.number}")
        return "::".join(parts)


def _cells(text: Any) -> List[str]:
    """Разбить строку-цитату на ячейки (артефакты дампа `A=` снимаются)."""
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


def parse_shifr(*texts: Any) -> Optional[str]:
    for text in texts:
        match = _SHIFR_RE.search(str(text or ""))
        if match:
            return match.group(1).upper()
    return None


def _clean_name(raw: Optional[str]) -> Optional[str]:
    text = re.sub(r"\s+", " ", str(raw or "")).strip(" .:-—")
    # в дорожных сметах после названия часто идёт «Поз.: 33-35» — это не имя
    text = re.sub(r"\s*Поз\.?:\s*[\d,\s-]+$", "", text).strip()
    if not text or len(text) > 90:
        return None
    low = text.lower()
    if low in ("работ и затрат", "строительства"):
        return None
    return text


def parse_road_marker(*texts: Any) -> Optional[RoadMarker]:
    """Найти маркер раздела дорожной сметы по тексту строки (в любой колонке)."""
    parts: List[str] = []
    for text in texts:
        if text:
            parts.extend(_cells(text))
    joined = " | ".join(parts)
    if not joined:
        return None
    shifr = parse_shifr(joined)
    for kind, pattern in (("razdel", _RAZDEL_RE), ("glava", _GLAVA_RE)):
        match = pattern.search(joined)
        if match:
            name = _clean_name(match.group(2))
            if kind == "glava" and not name:
                continue
            return RoadMarker(kind=kind, number=match.group(1), name=name, shifr=shifr)
    return None


def _row_summarizable(row: Dict[str, Any]) -> bool:
    return is_summarizable(
        entity_type=row.get("entity_type") or "PRODUCT",
        layout_status=row.get("layout_status"),
        quantity_value=row.get("quantity_value"),
        unit_normalized=row.get("quantity_unit_normalized"),
        name=row.get("product_name_normalized") or row.get("product_name_raw"),
    )


def _row_aggregate(row: Dict[str, Any]) -> bool:
    return is_aggregate_row(
        name=row.get("product_name_normalized") or row.get("product_name_raw"),
        unit_normalized=row.get("quantity_unit_normalized"),
        quantity_value=row.get("quantity_value"),
    )


def _explicit_total(row: Dict[str, Any]) -> Optional[float]:
    """Итог раздела берём ТОЛЬКО из явной строки итога (агрегатной)."""
    if not _row_aggregate(row):
        return None
    value = row.get("total_price_value")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def build_road_sections(
    rows: Sequence[Dict[str, Any]], *, coverage_min: float = COVERAGE_MIN
) -> Dict[str, Any]:
    """Собрать дорожные разделы из строк-фактов (детерминированно, без БД).

    Каждая строка — mapping с `source_quote`, `product_name_raw`,
    `quantity_value`, `quantity_unit_normalized`, `total_price_value`, `layout_status`.
    """
    sections: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    shifr_to_code: Dict[Any, str] = {}
    current: Optional[str] = None
    residue: List[Dict[str, Any]] = []

    for row in rows or []:
        sheet = row.get("page_or_sheet") or row.get("sheet")
        sheet = str(sheet) if sheet else None
        marker = parse_road_marker(row.get("source_quote"))
        if marker is None:
            # маркер может прийти из исходных колонок строки
            marker = parse_road_marker(
                row.get("source_quote"), row.get("product_name_raw"),
                row.get("product_name_normalized"),
            )
        if marker is not None:
            current = marker.code(sheet)
            if current not in sections:
                sections[current] = {
                    "section_code": current,
                    "section_name": marker.name or marker.number,
                    "page_or_sheet": sheet,
                    "marker_kind": marker.kind,
                    "marker_number": marker.number,
                    "shifrs": [],
                    "materials": [],
                    "computed_sum": 0.0,
                    "summarizable_rows": 0,
                    "total_rows": 0,
                    "aggregate_rows": 0,
                    "total_value": None,
                    "total_source": None,
                }
                order.append(current)
            section = sections[current]
            if marker.name and section["section_name"] == marker.number:
                section["section_name"] = marker.name
            if marker.shifr and marker.shifr not in section["shifrs"]:
                section["shifrs"].append(marker.shifr)
                shifr_to_code.setdefault(marker.shifr, current)
                if sheet:
                    shifr_to_code.setdefault((sheet, marker.shifr), current)
        else:
            shifr = parse_shifr(row.get("source_quote"))
            if shifr and sheet and (sheet, shifr) in shifr_to_code:
                current = shifr_to_code[(sheet, shifr)]
            elif shifr and shifr in shifr_to_code:
                current = shifr_to_code[shifr]

        if current is None:
            residue.append(row)
            continue

        section = sections[current]
        if _row_aggregate(row):
            section["aggregate_rows"] += 1
            value = _explicit_total(row)
            if value is not None and section["total_source"] is None:
                section["total_value"] = value
                section["total_source"] = "SECTION_TOTAL"
            continue
        if not _row_summarizable(row):
            continue
        section["summarizable_rows"] += 1
        value = row.get("total_price_value")
        if value is not None:
            try:
                section["computed_sum"] += float(value)
                section["total_rows"] += 1
            except (TypeError, ValueError):
                pass
        section["materials"].append(row)

    out: List[Dict[str, Any]] = []
    for code in order:
        section = sections[code]
        coverage = (section["total_rows"] / section["summarizable_rows"]
                    if section["summarizable_rows"] else 0.0)
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
    }
