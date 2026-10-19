"""LIGHTING_SECTION_TEMPLATES_V1 (3A Phase 2) — шаблонный слой светотехники.

Светотехнические сметы/ведомости используют тот же текстовый маркер, что и
дорожные: «Раздел N <Название>» / «Глава N <Название>», иногда «Секция N».
Позиция колонки нестабильна, поэтому детектор работает по тексту ячейки
(`source_quote`), а не по номеру колонки и не по типу файла.

Что делает слой:

  * распознаёт раздел по тексту (`parse_lighting_marker`);
  * `section_name` берёт из текста после номера;
  * identity — лист + номер: `lighting::<sheet>::razdel N` / `glava N` / `sekcia N`,
    чтобы одноимённые разделы из разных листов не сливались;
  * шифры `ЛС-*` / `СР-*` / `ОС-*` — только fallback identity;
  * в сумму включает ТОЛЬКО canonical summarizable-материалы
    (`section_detector.is_summarizable`), агрегаты не суммирует;
  * total не обязателен: `SECTION_TOTAL`, иначе `COMPUTED_SUM` /
    `COMPUTED_SUM_UNRELIABLE`; раздел без total остаётся контейнером материалов;
  * непривязанное честно отдаёт в `RESIDUE`.

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

LIGHTING_CODE_PREFIX = "lighting"
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
_SHIFR_RE = re.compile(r"\b([А-ЯЁA-Z]{2}(?:-\d{2})+)\b")
_TOTAL_LABEL_RE = re.compile(r"^\s*(итого|всего)\b", re.IGNORECASE)


@dataclass
class LightingMarker:
    kind: str                 # "razdel" | "glava" | "sekcia"
    number: str
    name: Optional[str] = None
    shifr: Optional[str] = None

    def code(self, sheet: Optional[str] = None) -> str:
        parts = [LIGHTING_CODE_PREFIX]
        if sheet:
            parts.append(str(sheet))
        parts.append(f"{self.kind} {self.number}")
        return "::".join(parts)


def _cells(text: Any) -> List[str]:
    """Разбить цитату на ячейки (артефакты `A=` снимаются)."""
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
    text = str(raw).strip(" .:;-—\t")
    text = re.sub(r"\s+", " ", text)
    if not text:
        return None
    low = text.lower()
    if low.startswith(("итого", "всего")) or low in ("раздел", "глава", "секция"):
        return None
    return text[:90]


def parse_lighting_marker(*texts: Any) -> Optional[LightingMarker]:
    """Распознать маркер раздела светотехники по любому из текстов."""
    for text in texts:
        if not text:
            continue
        for cell in _cells(text):
            for kind, regex in (("razdel", _RAZDEL_RE), ("glava", _GLAVA_RE),
                                ("sekcia", _SEKCIA_RE)):
                m = regex.search(cell)
                if not m:
                    continue
                number = m.group(1)
                name = _clean_name(m.group(2))
                if not name:
                    # Название может лежать в следующей колонке той же строки.
                    cells = _cells(text)
                    try:
                        idx = cells.index(cell)
                    except ValueError:
                        idx = -1
                    if 0 <= idx < len(cells) - 1:
                        nxt = cells[idx + 1]
                        if not _SHIFR_RE.fullmatch(nxt):
                            name = _clean_name(nxt)
                return LightingMarker(kind=kind, number=number, name=name)
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
    value = row.get("total_price_value")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _is_total_label(row: Dict[str, Any]) -> bool:
    name = str(row.get("product_name_raw") or row.get("product_name_normalized") or "")
    return bool(_TOTAL_LABEL_RE.match(name))


def build_lighting_sections(
    rows: Sequence[Dict[str, Any]], *, coverage_min: float = COVERAGE_MIN
) -> Dict[str, Any]:
    """Собрать разделы светотехники из строк-фактов (детерминированно, без БД)."""
    sections: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    shifr_to_code: Dict[Any, str] = {}
    current: Optional[str] = None
    residue: List[Dict[str, Any]] = []

    for row in rows or []:
        sheet = row.get("page_or_sheet") or row.get("sheet")
        sheet = str(sheet) if sheet else None
        marker = parse_lighting_marker(row.get("source_quote"))
        if marker is None:
            marker = parse_lighting_marker(
                row.get("product_name_raw"), row.get("product_name_normalized")
            )
        if marker is not None and marker.shifr is None:
            sh = _SHIFR_RE.search(str(row.get("source_quote") or ""))
            if sh:
                marker.shifr = sh.group(1)
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
            sh = _SHIFR_RE.search(str(row.get("source_quote") or ""))
            if sh:
                key = sh.group(1)
                if sheet and (sheet, key) in shifr_to_code:
                    current = shifr_to_code[(sheet, key)]
                else:
                    current = shifr_to_code.get(key, current)

        if current is None:
            residue.append(row)
            continue

        section = sections[current]
        if _is_total_label(row):
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
        "template": "lighting_section_templates_v1",
    }
