"""FLOORING_SECTION_TEMPLATES_V1 — обёртка над общим sheet-движком.

Flooring-оценки: xlsx/прайс-листы и OCR-PDF. Текстовые маркеры
«Раздел/Глава/Секция/Участок/Лот N» используются, если есть; иначе
контейнером служит `page_or_sheet` (`page_N_table_M`, лист xlsx).
Identity включает лист или номер документа, поэтому одноимённые разделы из
разных файлов не сливаются. Строки без маркера и страницы — честный RESIDUE;
numeric fake names отбрасываются; в сумму только canonical summarizable.

Модуль read-only: не пишет в БД и не трогает scoring / medal / queue.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from .sheet_section_templates import (
    COVERAGE_MIN,
    SheetMarker as FlooringMarker,
    build_sheet_sections,
    parse_sheet_marker,
)

FLOORING_CODE_PREFIX = "flooring"
TEMPLATE_VERSION = "flooring_section_templates_v1"


def parse_flooring_marker(*texts: Any) -> Optional[FlooringMarker]:
    return parse_sheet_marker(*texts)


def build_flooring_sections(
    rows: Sequence[Dict[str, Any]],
    *,
    coverage_min: float = COVERAGE_MIN,
    page_fallback: bool = True,
) -> Dict[str, Any]:
    return build_sheet_sections(
        rows,
        prefix=FLOORING_CODE_PREFIX,
        template=TEMPLATE_VERSION,
        coverage_min=coverage_min,
        page_fallback=page_fallback,
    )
