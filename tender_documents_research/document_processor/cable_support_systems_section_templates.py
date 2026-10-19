"""CABLE_SUPPORT_SYSTEMS_SECTION_TEMPLATES_V1 — обёртка общего sheet-движка.

Кабеленесущие системы (лотки, кабель-каналы, муфты, провода): маркеры
«Раздел/Глава/Секция/Участок/Лот N» используются, если есть; иначе контейнер —
`page_or_sheet` (`page_N_table_M`, лист xlsx). Identity включает лист или номер
документа, поэтому одноимённые разделы из разных файлов не сливаются.

Строки без маркера и без страницы — честный RESIDUE; numeric fake names
отбрасываются; в сумму только canonical summarizable-материалы.
Модуль read-only: не пишет в БД и не трогает scoring / medal / queue.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from .sheet_section_templates import (
    COVERAGE_MIN,
    SheetMarker as CableSupportMarker,
    build_sheet_sections,
    parse_sheet_marker,
)

CABLE_SUPPORT_CODE_PREFIX = "cable_support_systems"
TEMPLATE_VERSION = "cable_support_systems_section_templates_v1"


def parse_cable_support_marker(*texts: Any) -> Optional[CableSupportMarker]:
    return parse_sheet_marker(*texts)


def build_cable_support_sections(
    rows: Sequence[Dict[str, Any]],
    *,
    coverage_min: float = COVERAGE_MIN,
    page_fallback: bool = True,
) -> Dict[str, Any]:
    return build_sheet_sections(
        rows,
        prefix=CABLE_SUPPORT_CODE_PREFIX,
        template=TEMPLATE_VERSION,
        coverage_min=coverage_min,
        page_fallback=page_fallback,
    )
